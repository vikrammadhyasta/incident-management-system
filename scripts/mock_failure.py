#!/usr/bin/env python3
"""
mock_failure.py — Simulates a cascading infrastructure failure scenario.

Scenario:
  1. RDBMS primary node fails (P0)
  2. MCP Host loses connectivity due to DB failure (P0)
  3. Cache cluster eviction storm begins (P2)
  4. Async queue consumer lag spikes (P1)
  5. API gateway starts returning 500s (P1)

Usage:
  python scripts/mock_failure.py --url http://localhost:8000
  python scripts/mock_failure.py --url http://localhost:8000 --burst 200
"""

import asyncio
import argparse
import json
import time
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    exit(1)


BASE_URL = "http://localhost:8000"
INGEST_ENDPOINT = "/api/v1/signals/ingest"


async def send_signals(client: httpx.AsyncClient, signals: list[dict], label: str):
    print(f"\n{'='*60}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending: {label}")
    print(f"  Signals: {len(signals)}")
    try:
        resp = await client.post(
            f"{BASE_URL}{INGEST_ENDPOINT}",
            json={"signals": signals},
            timeout=10.0,
        )
        data = resp.json()
        print(f"  ✓ Queued: {data.get('queued')}, Dropped: {data.get('dropped')}")
        return data
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return None


def make_signal(component_id, component_type, message, severity="CRITICAL",
                error_code=None, latency_ms=None, metadata=None):
    return {
        "component_id": component_id,
        "component_type": component_type,
        "message": message,
        "severity": severity,
        "error_code": error_code,
        "latency_ms": latency_ms,
        "metadata": metadata or {},
        "source_host": f"{component_id.lower().replace('_', '-')}-host",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def run_scenario(burst: int = 100):
    async with httpx.AsyncClient() as client:
        # ── Check backend health ────────────────────────────────────────────────
        print("\n🔍 Checking backend health...")
        try:
            resp = await client.get(f"{BASE_URL}/health", timeout=5.0)
            health = resp.json()
            print(f"  Status: {health.get('status')}")
            print(f"  PostgreSQL: {health.get('postgres')}")
            print(f"  MongoDB: {health.get('mongodb')}")
            print(f"  Redis: {health.get('redis')}")
        except Exception as e:
            print(f"  ✗ Backend unreachable: {e}")
            print("  Make sure docker-compose is running!")
            return

        print("\n🚨 Starting cascading failure simulation...\n")
        await asyncio.sleep(1)

        # ── Step 1: RDBMS Primary Failure ───────────────────────────────────────
        rdbms_signals = [
            make_signal(
                "POSTGRES_PRIMARY_01", "RDBMS",
                "FATAL: connection to server at '10.0.1.15' failed: Connection refused",
                error_code="PGCONN_REFUSED",
            ),
            make_signal(
                "POSTGRES_PRIMARY_01", "RDBMS",
                "pg_isready check FAILED — primary node not accepting connections",
                error_code="PGCONN_REFUSED",
            ),
            make_signal(
                "POSTGRES_REPLICA_01", "RDBMS",
                "Replica lag: 8.2 GB behind primary — replication stream broken",
                severity="ERROR",
                error_code="REPLICATION_LAG",
            ),
        ]
        await send_signals(client, rdbms_signals, "RDBMS Primary Node Failure (P0)")
        await asyncio.sleep(2)

        # ── Step 2: MCP Host Failure (cascades from RDBMS) ─────────────────────
        mcp_signals = [
            make_signal(
                "MCP_HOST_CLUSTER_02", "MCP_HOST",
                "MCP Host unreachable — health probe timeout after 30s",
                error_code="MCP_HEALTH_TIMEOUT",
                latency_ms=30000,
            ),
            make_signal(
                "MCP_HOST_CLUSTER_02", "MCP_HOST",
                "Service mesh circuit breaker OPEN — downstream DB dependency failing",
                error_code="CIRCUIT_BREAKER_OPEN",
                metadata={"triggered_by": "POSTGRES_PRIMARY_01", "cascade": True},
            ),
        ]
        await send_signals(client, mcp_signals, "MCP Host Cascade Failure (P0)")
        await asyncio.sleep(2)

        # ── Step 3: Cache Eviction Storm ────────────────────────────────────────
        # Simulate 100 signals for CACHE_CLUSTER_01 — debounce should create 1 WI
        cache_signals = [
            make_signal(
                "CACHE_CLUSTER_01", "CACHE",
                f"Cache eviction burst #{i+1}: hit rate dropped to {max(5, 80 - i)}%",
                severity="ERROR",
                error_code="CACHE_EVICTION_STORM",
                latency_ms=350 + i * 2,
            )
            for i in range(burst)
        ]
        await send_signals(
            client, cache_signals,
            f"Cache Eviction Storm — {burst} signals → 1 WorkItem (debounce test)"
        )
        await asyncio.sleep(2)

        # ── Step 4: Queue Consumer Lag ──────────────────────────────────────────
        queue_signals = [
            make_signal(
                "EVENT_QUEUE_PAYMENTS", "ASYNC_QUEUE",
                f"Consumer lag: {48000 + i * 500} messages — processing halted",
                severity="ERROR",
                error_code="CONSUMER_LAG_CRITICAL",
                metadata={"lag_messages": 48000 + i * 500, "topic": "payment-events"},
            )
            for i in range(10)
        ]
        await send_signals(client, queue_signals, "Async Queue Consumer Lag (P1)")
        await asyncio.sleep(2)

        # ── Step 5: API Gateway 5xx Spike ──────────────────────────────────────
        api_signals = [
            make_signal(
                "API_GATEWAY_PROD", "API",
                f"HTTP 500 error rate: {12 + i * 0.5:.1f}% (SLO threshold: 1%)",
                severity="ERROR",
                error_code="HTTP_500_SPIKE",
                latency_ms=8000 + i * 100,
                metadata={"error_rate_pct": 12 + i * 0.5, "p99_latency_ms": 8000 + i * 100},
            )
            for i in range(15)
        ]
        await send_signals(client, api_signals, "API Gateway 5xx Spike (P1)")
        await asyncio.sleep(2)

        # ── Summary ─────────────────────────────────────────────────────────────
        print("\n" + "="*60)
        print("📊 SIMULATION COMPLETE")
        print("="*60)

        try:
            resp = await client.get(f"{BASE_URL}/api/v1/signals/metrics", timeout=5.0)
            m = resp.json()
            print(f"\nIngestion Metrics:")
            print(f"  Total signals received : {m.get('signals_received', '?')}")
            print(f"  Total signals persisted: {m.get('signals_persisted', '?')}")
            print(f"  Work items created     : {m.get('work_items_created', '?')}")
            print(f"  Queue depth            : {m.get('queue_depth', '?')}")
        except Exception as e:
            print(f"  (Could not fetch metrics: {e})")

        try:
            resp = await client.get(f"{BASE_URL}/api/v1/dashboard/stats", timeout=5.0)
            s = resp.json()
            print(f"\nDashboard Stats:")
            print(f"  OPEN incidents         : {s.get('total_open', '?')}")
            print(f"  INVESTIGATING          : {s.get('total_investigating', '?')}")
            print(f"  P0 active              : {s.get('p0_active', '?')}")
            print(f"  P1 active              : {s.get('p1_active', '?')}")
        except Exception as e:
            print(f"  (Could not fetch stats: {e})")

        print("\n✅ Open http://localhost:3000 to see incidents in the dashboard")
        print("="*60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IMS Mock Failure Simulator")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend URL")
    parser.add_argument("--burst", type=int, default=100,
                        help="Number of cache signals to send (tests debounce logic)")
    args = parser.parse_args()
    BASE_URL = args.url
    asyncio.run(run_scenario(burst=args.burst))
