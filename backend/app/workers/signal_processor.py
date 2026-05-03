"""
Signal Processing Worker — The Producer Engine.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Architecture:
  Ingestion API → asyncio.Queue (bounded) → Worker Pool → DB sinks

Key design decisions:
  1. Bounded asyncio.Queue provides backpressure (prevents OOM on slow DB).
  2. Debounce dict tracks per-component signal windows.
  3. Worker pool (N coroutines) drains the queue concurrently.
  4. MongoDB gets every raw signal; PostgreSQL gets only 1 WorkItem per debounce window.
  5. Redis cache is updated after every WorkItem write.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID

import structlog
from bson import ObjectId

from app.core.config import settings
from app.db.connections import get_db_session, get_mongo_db, get_redis
from app.models.orm import ComponentType, WorkItem
from app.models.schemas import SignalPayload
from app.services.alert_strategy import evaluate_alert

log = structlog.get_logger()


# ── Metrics (in-process counters) ─────────────────────────────────────────────

@dataclass
class ProcessorMetrics:
    signals_received: int = 0
    signals_persisted: int = 0
    signals_dropped: int = 0
    work_items_created: int = 0
    work_items_updated: int = 0
    # Rolling window for throughput
    _window_start: float = field(default_factory=time.monotonic)
    _window_count: int = 0

    def record_received(self, n: int = 1):
        self.signals_received += n
        self._window_count += n

    def record_dropped(self, n: int = 1):
        self.signals_dropped += n

    def flush_throughput(self) -> float:
        now = time.monotonic()
        elapsed = now - self._window_start
        rate = self._window_count / elapsed if elapsed > 0 else 0
        self._window_start = now
        self._window_count = 0
        return rate


metrics = ProcessorMetrics()


# ── Debounce state ─────────────────────────────────────────────────────────────

@dataclass
class DebounceWindow:
    work_item_id: Optional[UUID]
    signal_ids: list
    window_start: float
    count: int = 0


_debounce_windows: Dict[str, DebounceWindow] = {}
_debounce_lock = asyncio.Lock()


# ── Signal Queue (bounded — the backpressure mechanism) ───────────────────────

_signal_queue: asyncio.Queue[SignalPayload] = asyncio.Queue(
    maxsize=settings.SIGNAL_BUFFER_SIZE
)


def get_queue() -> asyncio.Queue:
    return _signal_queue


async def enqueue_signals(signals: list[SignalPayload]) -> tuple[int, int]:
    """
    Non-blocking enqueue. Returns (queued, dropped).
    Signals are dropped when buffer is full — never block the HTTP handler.
    """
    queued = dropped = 0
    for sig in signals:
        try:
            _signal_queue.put_nowait(sig)
            metrics.record_received()
            queued += 1
        except asyncio.QueueFull:
            metrics.record_dropped()
            dropped += 1
    return queued, dropped


# ── Core Worker ────────────────────────────────────────────────────────────────

async def _persist_signal_to_mongo(signal: SignalPayload) -> str:
    """Write raw signal to MongoDB (Data Lake). Returns inserted document ID."""
    db = get_mongo_db()
    doc = {
        "component_id": signal.component_id,
        "component_type": signal.component_type.value,
        "error_code": signal.error_code,
        "message": signal.message,
        "severity": signal.severity,
        "latency_ms": signal.latency_ms,
        "metadata": signal.metadata or {},
        "source_host": signal.source_host,
        "timestamp": signal.timestamp or datetime.now(timezone.utc),
        "ingested_at": datetime.now(timezone.utc),
    }
    result = await db.signals.insert_one(doc)
    metrics.signals_persisted += 1
    return str(result.inserted_id)


async def _get_or_create_work_item(
    signal: SignalPayload, mongo_signal_id: str
) -> UUID:
    """
    Debounce logic:
      - If a WorkItem for component_id exists within the debounce window,
        increment its counter and link the new signal ID.
      - Otherwise, create a new WorkItem and start a new window.
    """
    component_key = signal.component_id
    now = time.monotonic()

    async with _debounce_lock:
        window = _debounce_windows.get(component_key)
        window_expired = (
            window is None
            or (now - window.window_start) >= settings.DEBOUNCE_WINDOW_SECONDS
        )

        if window_expired:
            # New debounce window — create a WorkItem in PostgreSQL
            alert_ctx = evaluate_alert(
                signal.component_id, signal.component_type, signal.message
            )
            async with get_db_session() as session:
                wi = WorkItem(
                    component_id=signal.component_id,
                    component_type=signal.component_type,
                    priority=alert_ctx.priority,
                    title=f"{alert_ctx.priority}: {signal.component_type.value} failure on {signal.component_id}",
                    signal_count=1,
                    start_time=signal.timestamp or datetime.now(timezone.utc),
                )
                session.add(wi)
                await session.flush()
                work_item_id = wi.id
                await session.commit()

            _debounce_windows[component_key] = DebounceWindow(
                work_item_id=work_item_id,
                signal_ids=[mongo_signal_id],
                window_start=now,
                count=1,
            )
            metrics.work_items_created += 1

            # Update Redis dashboard cache
            await _update_redis_cache(work_item_id, signal, alert_ctx)

            log.info(
                "work_item_created",
                work_item_id=str(work_item_id),
                component_id=signal.component_id,
                priority=alert_ctx.priority,
            )
            return work_item_id

        else:
            # Within window — increment counter, link signal
            window.count += 1
            window.signal_ids.append(mongo_signal_id)

            # Batch-update PostgreSQL signal_count every 10 signals to reduce writes
            if window.count % 10 == 0:
                async with get_db_session() as session:
                    from sqlalchemy import update as sa_update
                    await session.execute(
                        sa_update(WorkItem)
                        .where(WorkItem.id == window.work_item_id)
                        .values(signal_count=window.count)
                    )
                    await session.commit()
                metrics.work_items_updated += 1

            # Link signal in MongoDB
            db = get_mongo_db()
            await db.signals.update_one(
                {"_id": ObjectId(mongo_signal_id)},
                {"$set": {"work_item_id": str(window.work_item_id)}},
            )

            return window.work_item_id


async def _update_redis_cache(work_item_id, signal, alert_ctx) -> None:
    """Update hot-path Redis dashboard state."""
    try:
        r = await get_redis()
        key = f"wi:{work_item_id}"
        await r.hset(key, mapping={
            "id": str(work_item_id),
            "component_id": signal.component_id,
            "component_type": signal.component_type.value,
            "priority": alert_ctx.priority.value,
            "status": "OPEN",
            "title": f"{alert_ctx.priority}: {signal.component_type.value} failure on {signal.component_id}",
            "signal_count": 1,
            "start_time": (signal.timestamp or datetime.now(timezone.utc)).isoformat(),
        })
        await r.expire(key, 3600)  # 1 hour TTL
        # Add to active incidents sorted set (score = priority numeric)
        priority_score = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        score = priority_score.get(alert_ctx.priority.value, 3)
        await r.zadd("active_incidents", {str(work_item_id): score})
    except Exception as e:
        log.warning("redis_cache_update_failed", error=str(e))


async def _process_signal(signal: SignalPayload) -> None:
    """Full pipeline for a single signal."""
    try:
        mongo_id = await _persist_signal_to_mongo(signal)
        await _get_or_create_work_item(signal, mongo_id)
    except Exception as e:
        log.error("signal_processing_error", error=str(e), component=signal.component_id)


# ── Worker Pool ────────────────────────────────────────────────────────────────

async def signal_worker(worker_id: int) -> None:
    """A single worker coroutine that drains from the shared queue."""
    log.info("signal_worker_started", worker_id=worker_id)
    while True:
        try:
            signal = await asyncio.wait_for(_signal_queue.get(), timeout=1.0)
            await _process_signal(signal)
            _signal_queue.task_done()
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            log.info("signal_worker_stopped", worker_id=worker_id)
            return
        except Exception as e:
            log.error("worker_error", worker_id=worker_id, error=str(e))


async def metrics_reporter() -> None:
    """Prints throughput metrics every N seconds."""
    while True:
        try:
            await asyncio.sleep(settings.METRICS_INTERVAL_SECONDS)
            rate = metrics.flush_throughput()
            log.info(
                "throughput_metrics",
                signals_per_sec=f"{rate:.1f}",
                queue_depth=_signal_queue.qsize(),
                total_received=metrics.signals_received,
                total_persisted=metrics.signals_persisted,
                total_dropped=metrics.signals_dropped,
                work_items_created=metrics.work_items_created,
            )
        except asyncio.CancelledError:
            return


_worker_tasks: list[asyncio.Task] = []


async def start_workers() -> None:
    """Spawn worker pool + metrics reporter."""
    global _worker_tasks
    for i in range(settings.SIGNAL_WORKER_CONCURRENCY):
        task = asyncio.create_task(signal_worker(i), name=f"signal_worker_{i}")
        _worker_tasks.append(task)
    reporter = asyncio.create_task(metrics_reporter(), name="metrics_reporter")
    _worker_tasks.append(reporter)
    log.info("worker_pool_started", workers=settings.SIGNAL_WORKER_CONCURRENCY)


async def stop_workers() -> None:
    """Graceful shutdown — drain queue then cancel workers."""
    log.info("Draining signal queue...")
    try:
        await asyncio.wait_for(_signal_queue.join(), timeout=10.0)
    except asyncio.TimeoutError:
        log.warning("Queue drain timed out; forcing shutdown")
    for task in _worker_tasks:
        task.cancel()
    await asyncio.gather(*_worker_tasks, return_exceptions=True)
    log.info("Worker pool stopped")
