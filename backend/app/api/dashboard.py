"""
Dashboard & Health API — /api/v1/dashboard, /health
"""

import time
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.db.connections import get_db_session, get_mongo_db, get_redis
from app.models.orm import WorkItem, WorkItemStatus
from app.models.schemas import DashboardStats, HealthResponse
from app.workers.signal_processor import get_queue

router = APIRouter(tags=["Dashboard"])
log = structlog.get_logger()

_start_time = time.monotonic()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint. Probes all dependencies."""
    pg_status = mongo_status = redis_status = "ok"

    try:
        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        pg_status = f"error: {str(e)[:50]}"

    try:
        db = get_mongo_db()
        await db.command("ping")
    except Exception as e:
        mongo_status = f"error: {str(e)[:50]}"

    try:
        r = await get_redis()
        await r.ping()
    except Exception as e:
        redis_status = f"error: {str(e)[:50]}"

    overall = "healthy" if all(
        s == "ok" for s in [pg_status, mongo_status, redis_status]
    ) else "degraded"

    return HealthResponse(
        status=overall,
        postgres=pg_status,
        mongodb=mongo_status,
        redis=redis_status,
        buffer_depth=get_queue().qsize(),
        uptime_seconds=round(time.monotonic() - _start_time, 2),
    )


@router.get("/api/v1/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats():
    """Aggregate dashboard statistics."""
    async with get_db_session() as session:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Status counts
        status_counts = {s: 0 for s in WorkItemStatus}
        rows = await session.execute(
            select(WorkItem.status, func.count().label("cnt"))
            .group_by(WorkItem.status)
        )
        for row in rows:
            status_counts[row.status] = row.cnt

        # P0/P1 active
        p0_result = await session.execute(
            select(func.count()).where(
                WorkItem.priority == "P0",
                WorkItem.status.in_(["OPEN", "INVESTIGATING"]),
            )
        )
        p1_result = await session.execute(
            select(func.count()).where(
                WorkItem.priority == "P1",
                WorkItem.status.in_(["OPEN", "INVESTIGATING"]),
            )
        )

        # Closed today
        closed_today = await session.execute(
            select(func.count()).where(
                WorkItem.status == WorkItemStatus.CLOSED,
                WorkItem.closed_time >= today_start,
            )
        )

        # Avg MTTR
        mttr_result = await session.execute(
            select(func.avg(WorkItem.mttr_seconds)).where(
                WorkItem.mttr_seconds.isnot(None)
            )
        )

    # Signals in last hour from MongoDB
    db = get_mongo_db()
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    signals_last_hour = await db.signals.count_documents(
        {"ingested_at": {"$gte": one_hour_ago}}
    )

    return DashboardStats(
        total_open=status_counts.get(WorkItemStatus.OPEN, 0),
        total_investigating=status_counts.get(WorkItemStatus.INVESTIGATING, 0),
        total_resolved=status_counts.get(WorkItemStatus.RESOLVED, 0),
        total_closed_today=closed_today.scalar_one(),
        p0_active=p0_result.scalar_one(),
        p1_active=p1_result.scalar_one(),
        avg_mttr_seconds=mttr_result.scalar_one(),
        signals_last_hour=signals_last_hour,
    )


@router.get("/api/v1/dashboard/active")
async def active_incidents():
    """
    Fast path: return active incidents from Redis sorted set.
    Falls back to PostgreSQL if Redis is empty.
    """
    try:
        r = await get_redis()
        wids = await r.zrange("active_incidents", 0, -1, withscores=True)
        if wids:
            pipeline = r.pipeline()
            for wid, _ in wids:
                pipeline.hgetall(f"wi:{wid}")
            results = await pipeline.execute()
            incidents = [r for r in results if r]
            return {"source": "cache", "incidents": incidents}
    except Exception as e:
        log.warning("redis_read_failed", error=str(e))

    # Fallback to PostgreSQL
    async with get_db_session() as session:
        result = await session.execute(
            select(WorkItem)
            .where(WorkItem.status.in_(["OPEN", "INVESTIGATING"]))
            .order_by(WorkItem.priority, WorkItem.created_at.desc())
            .limit(50)
        )
        items = result.scalars().all()
        return {
            "source": "database",
            "incidents": [
                {
                    "id": str(wi.id),
                    "component_id": wi.component_id,
                    "priority": wi.priority.value,
                    "status": wi.status.value,
                    "title": wi.title,
                    "signal_count": wi.signal_count,
                    "start_time": wi.start_time.isoformat(),
                }
                for wi in items
            ],
        }
