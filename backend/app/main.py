"""
IMS Backend — FastAPI Application Entry Point
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.dashboard import router as dashboard_router
from app.api.signals import router as signals_router
from app.api.work_items import router as work_items_router
from app.db.connections import connect_all, disconnect_all
from app.workers.signal_processor import start_workers, stop_workers

log = structlog.get_logger()

# ── Rate Limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── App Factory ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Incident Management System",
    description="Mission-Critical IMS for distributed infrastructure monitoring",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Lifecycle ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    log.info("IMS backend starting up...")
    await connect_all()
    await start_workers()
    log.info("IMS backend ready ✓")


@app.on_event("shutdown")
async def shutdown():
    log.info("IMS backend shutting down...")
    await stop_workers()
    await disconnect_all()
    log.info("IMS backend stopped ✓")


# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(signals_router)
app.include_router(work_items_router)
app.include_router(dashboard_router)


# ── Root ───────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    return {"service": "IMS Backend", "version": "1.0.0", "docs": "/docs"}
