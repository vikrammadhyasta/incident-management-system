"""
Signal Ingestion API — /api/v1/signals
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Endpoints:
  POST /ingest         — Single or batch signal ingestion (REST)
  WS   /ws/ingest      — WebSocket high-throughput ingestion

Rate limiting: slowapi (token bucket per IP).
"""

import json

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.models.schemas import SignalBatch, SignalIngestionResponse, SignalPayload
from app.workers.signal_processor import enqueue_signals, get_queue, metrics

router = APIRouter(prefix="/api/v1/signals", tags=["Signal Ingestion"])

limiter = Limiter(key_func=get_remote_address)


@router.post("/ingest", response_model=SignalIngestionResponse)
@limiter.limit("5000/minute")
async def ingest_signals(request: Request, batch: SignalBatch):
    """
    Ingest a batch of signals (up to 500 per request).
    Non-blocking: signals are queued for async processing.
    Returns immediately with accepted/dropped counts.
    """
    queued, dropped = await enqueue_signals(batch.signals)
    return SignalIngestionResponse(
        accepted=len(batch.signals),
        queued=queued,
        dropped=dropped,
        message=f"Queued {queued} signals. Buffer depth: {get_queue().qsize()}",
    )


@router.post("/ingest/single", response_model=SignalIngestionResponse)
@limiter.limit("5000/minute")
async def ingest_single(request: Request, signal: SignalPayload):
    """Ingest a single signal."""
    queued, dropped = await enqueue_signals([signal])
    return SignalIngestionResponse(
        accepted=1,
        queued=queued,
        dropped=dropped,
        message="Signal accepted" if queued else "Buffer full — signal dropped",
    )


@router.get("/metrics")
async def get_metrics():
    """Real-time ingestion metrics."""
    return {
        "signals_received": metrics.signals_received,
        "signals_persisted": metrics.signals_persisted,
        "signals_dropped": metrics.signals_dropped,
        "work_items_created": metrics.work_items_created,
        "work_items_updated": metrics.work_items_updated,
        "queue_depth": get_queue().qsize(),
        "queue_capacity": get_queue().maxsize,
        "buffer_utilization_pct": round(
            (get_queue().qsize() / get_queue().maxsize) * 100, 2
        ),
    }


@router.websocket("/ws/ingest")
async def ws_ingest(websocket: WebSocket):
    """
    WebSocket ingestion endpoint for high-throughput producers.
    Expects JSON-encoded SignalPayload per message.
    Responds with ack: {"status": "ok", "queued": N, "dropped": N}
    """
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                # Support both single and array
                if isinstance(data, list):
                    signals = [SignalPayload(**s) for s in data]
                else:
                    signals = [SignalPayload(**data)]

                queued, dropped = await enqueue_signals(signals)
                await websocket.send_json({
                    "status": "ok",
                    "queued": queued,
                    "dropped": dropped,
                })
            except Exception as e:
                await websocket.send_json({"status": "error", "detail": str(e)})
    except WebSocketDisconnect:
        pass
