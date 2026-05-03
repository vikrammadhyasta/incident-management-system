"""
Database connection managers.
- PostgreSQL via SQLAlchemy async (Source of Truth)
- MongoDB via Motor (Data Lake / Raw Signals)
- Redis via redis-py async (Hot-Path Cache)
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
import structlog
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

log = structlog.get_logger()

# ── SQLAlchemy (PostgreSQL) ────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


_pg_engine: AsyncEngine | None = None
_pg_session_factory: async_sessionmaker | None = None


def get_pg_engine() -> AsyncEngine:
    global _pg_engine
    if _pg_engine is None:
        _pg_engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
    return _pg_engine


def get_session_factory() -> async_sessionmaker:
    global _pg_session_factory
    if _pg_session_factory is None:
        _pg_session_factory = async_sessionmaker(
            get_pg_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _pg_session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    session = get_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ── MongoDB (Motor) ────────────────────────────────────────────────────────────

_mongo_client: AsyncIOMotorClient | None = None


def get_mongo_db() -> AsyncIOMotorDatabase:
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            maxPoolSize=50,
            serverSelectionTimeoutMS=5000,
        )
    return _mongo_client["ims_signals"]


# ── Redis ──────────────────────────────────────────────────────────────────────

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=30,
        )
    return _redis_client


# ── Lifecycle ──────────────────────────────────────────────────────────────────

async def connect_all() -> None:
    log.info("Connecting to databases...")
    # Warm up PG pool
    engine = get_pg_engine()
    async with engine.connect() as conn:
        await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    log.info("PostgreSQL connected")

    # Warm up Mongo
    db = get_mongo_db()
    await db.command("ping")
    log.info("MongoDB connected")

    # Warm up Redis
    r = await get_redis()
    await r.ping()
    log.info("Redis connected")


async def disconnect_all() -> None:
    global _mongo_client, _redis_client, _pg_engine
    if _pg_engine:
        await _pg_engine.dispose()
    if _mongo_client:
        _mongo_client.close()
    if _redis_client:
        await _redis_client.aclose()
    log.info("All database connections closed")
