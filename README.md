# 🚨 Incident Management System (IMS)

> Mission-critical distributed incident management platform built for high-throughput signal ingestion, intelligent deduplication, workflow-driven resolution, and mandatory Root Cause Analysis.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          SIGNAL PRODUCERS                               │
│   APIs │ MCP Hosts │ Caches │ Queues │ RDBMS │ NoSQL                    │
└────────────────────────────┬────────────────────────────────────────────┘
                             │  REST (batch) / WebSocket (stream)
                             ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    FASTAPI INGESTION LAYER                             │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Rate Limiter (slowapi) — 5000 req/min per IP                    │  │
│  └──────────────────────┬───────────────────────────────────────────┘  │
│                          │                                             │
│  ┌──────────────────────▼───────────────────────────────────────────┐  │
│  │  asyncio.Queue (bounded: 50,000 slots) ← BACKPRESSURE BOUNDARY   │  │
│  │  Signals dropped (not blocking) when queue is full               │  │
│  └──────────────────────┬───────────────────────────────────────────┘  │
│                          │  8 concurrent worker coroutines             │
│  ┌───────┬──────┬───────┬▼──────┬───────┬───────┬────────┬────────┐    │
│  │ W-0   │ W-1  │  W-2  │  W-3  │  W-4  │  W-5  │  W-6   │  W-7  │     │
│  └───────┴──────┴───────┴───────┴───────┴───────┴────────┴────────┘    │
│                          │                                             │
│  ┌──────────────────────▼───────────────────────────────────────────┐  │
│  │  DEBOUNCE ENGINE (in-memory, per component_id)                   │  │
│  │  Window: 10s │ Threshold: 100 signals → 1 Work Item              │  │
│  └──────┬────────────────────────────────────────┬──────────────────┘  │
│         │  Work Item created                     │  All raw signals    │
└─────────┼────────────────────────────────────────┼────────────────────-┘
          ▼                                         ▼
┌─────────────────────┐                 ┌────────────────────────────────┐
│   PostgreSQL 16     │                 │        MongoDB 7               │
│  (Source of Truth)  │                 │       (Data Lake)              │
│                     │                 │                                │
│  • work_items       │                 │  • signals (raw payloads)      │
│  • rca_records      │                 │  • work_item_id linkage        │
│  • status_          │                 │  • queryable audit log         │
│    transitions      │                 └────────────────────────────────┘
│  ACID transactions  │
└──────────┬──────────┘
           │  Cache invalidation
           ▼
┌─────────────────────┐
│     Redis 7         │
│   (Hot-Path Cache)  │
│                     │
│  • active_incidents │
│    (sorted set)     │
│  • wi:{id} hash     │
│  • 1hr TTL          │
└─────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       REACT FRONTEND                                    │
│ Dashboard │ Incident List │ Incident Detail │ RCA Form │ Signal Injector│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Backend API | **FastAPI + Python 3.12** | Native async/await, auto OpenAPI docs, pydantic v2 |
| Signal Buffer | **asyncio.Queue (bounded)** | Zero-dependency backpressure; prevents OOM on DB lag |
| Source of Truth | **PostgreSQL 16** | ACID transactions for Work Item + RCA writes |
| Data Lake | **MongoDB 7 (Motor)** | Flexible schema for high-volume raw signal documents |
| Hot-Path Cache | **Redis 7** | Sub-millisecond dashboard reads; sorted set for priority ordering |
| Rate Limiting | **slowapi** | Token-bucket per-IP; prevents ingestion cascades |
| Frontend | **React 18 + Vite** | Fast HMR, component-based, small bundle |
| Container | **Docker Compose** | One-command reproducible environment |

---

## Quick Start

### Prerequisites
- Docker + Docker Compose v2
- Git

### 1. Clone & Start

```bash
git clone https://github.com/YOUR_USERNAME/ims-zeotap.git
cd ims-zeotap
docker compose up --build
```

Wait ~30 seconds for all services to become healthy.

### 2. Access

| Service | URL |
|---------|-----|
| Frontend Dashboard | http://localhost:3000 |
| Backend API Docs | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |

### 3. Simulate a Failure

```bash
# Install httpx if needed
pip install httpx

# Run the cascading failure simulation
python scripts/mock_failure.py

# Or with a burst of 200 cache signals to test debouncing
python scripts/mock_failure.py --burst 200
```

---

## Running Tests

```bash
# Install test dependencies
cd backend
pip install -r requirements.txt

# Run unit tests
pytest tests/ -v

# With coverage
pytest tests/ -v --tb=short
```

Tests cover:
- ✅ RCA validation (all 8 categories, field length enforcement, end > start)
- ✅ Alert Strategy selection (P0/P1/P2/P3 per component type)
- ✅ State machine transitions (valid + invalid paths)
- ✅ CLOSED transition blocked without RCA
- ✅ CLOSED transition allowed with complete RCA + MTTR calculation

---

## API Reference

### Signal Ingestion

```bash
# Single signal
curl -X POST http://localhost:8000/api/v1/signals/ingest/single \
  -H "Content-Type: application/json" \
  -d '{
    "component_id": "POSTGRES_PRIMARY_01",
    "component_type": "RDBMS",
    "message": "Connection refused",
    "severity": "CRITICAL"
  }'

# Batch (up to 500 signals per request)
curl -X POST http://localhost:8000/api/v1/signals/ingest \
  -H "Content-Type: application/json" \
  -d '{"signals": [...]}'
```

### Work Item Lifecycle

```bash
# List all incidents (sorted by priority)
curl http://localhost:8000/api/v1/work-items

# Transition status
curl -X POST http://localhost:8000/api/v1/work-items/{id}/transition \
  -H "Content-Type: application/json" \
  -d '{"new_status": "INVESTIGATING", "notes": "Paging on-call team"}'

# Submit RCA (required before CLOSED)
curl -X POST http://localhost:8000/api/v1/work-items/{id}/rca \
  -H "Content-Type: application/json" \
  -d '{
    "incident_start": "2025-01-01T10:00:00Z",
    "incident_end": "2025-01-01T12:00:00Z",
    "root_cause_category": "Infrastructure Failure",
    "root_cause_detail": "Primary DB node ran out of disk space due to unrotated WAL logs.",
    "fix_applied": "Cleared old WAL logs and expanded EBS volume by 100GB.",
    "prevention_steps": "Implemented automated log rotation with 7-day retention policy."
  }'

# Close incident (only succeeds if RCA exists)
curl -X POST http://localhost:8000/api/v1/work-items/{id}/transition \
  -d '{"new_status": "CLOSED"}'
```

---

## Design Patterns Used

### 1. Strategy Pattern — Alert Prioritization

```
ComponentType → AlertStrategy → AlertContext(priority, channel, escalate)

RDBMS     → RDBMSAlertStrategy     → P0, pagerduty, escalate=True
MCP_HOST  → MCPHostAlertStrategy   → P0, pagerduty, escalate=True
CACHE     → CacheAlertStrategy     → P2, slack,     escalate=False
API       → APIAlertStrategy       → P1, slack,     escalate=False
...
```

New component types require only a new strategy class — zero changes to callers.

### 2. State Pattern — Work Item Lifecycle

```
OPEN ──► INVESTIGATING ──► RESOLVED ──► CLOSED
           ▲                  │
           └──────────────────┘ (re-open on regression)

Each state validates transitions and enforces invariants:
• ResolvedState.transition_to(CLOSED) → asserts RCA is complete
• ClosedState.transition_to(anything) → raises InvalidTransitionError
```

---

## Backpressure Handling

The system uses a **bounded asyncio.Queue** as the backpressure boundary:

```
Producer (HTTP handler)
    │
    │  put_nowait() — non-blocking
    ▼
┌─────────────────────────────┐
│  asyncio.Queue(maxsize=50000)│  ← BACKPRESSURE BOUNDARY
└─────────────────────────────┘
    │  get() — blocking workers
    ▼
Consumer Pool (8 workers)
    │
    ▼
MongoDB + PostgreSQL
```

**What happens when the queue is full?**
- `put_nowait()` raises `asyncio.QueueFull`
- The HTTP handler catches this and returns `dropped=N` in the response
- **The HTTP handler never blocks** — it always returns immediately
- Dropped signal count is tracked in `ProcessorMetrics`
- The `/api/v1/signals/metrics` endpoint exposes `buffer_utilization_pct`

This means: even if MongoDB/PostgreSQL become slow or unavailable, the ingestion API continues to accept signals (up to queue capacity) without cascading back pressure to callers.

---

## Non-Functional Features (Bonus Points)

### Security
- API rate limiting: 5,000 requests/minute per IP (slowapi)
- CORS configured for known origins
- Optional API key header (configurable via `API_KEY` env var)
- SQL injection prevention via SQLAlchemy ORM (parameterized queries)
- No raw SQL strings anywhere in the codebase

### Observability
- `/health` endpoint probes PostgreSQL, MongoDB, and Redis individually
- Throughput metrics printed to console every 5 seconds (configurable)
- `/api/v1/signals/metrics` returns real-time buffer stats
- Structured JSON logging via `structlog`
- Every state transition is audit-logged to `status_transitions` table

### Resilience
- DB connection pool pre-ping (`pool_pre_ping=True`) auto-reconnects
- Row-level locking (`SELECT ... FOR UPDATE`) on status transitions — prevents race conditions
- Graceful shutdown: queue is drained before workers stop (10s timeout)
- Redis failures are non-fatal — dashboard falls back to PostgreSQL
- All DB operations wrapped in try/catch with retry-friendly patterns

### Performance
- 8 concurrent async worker coroutines drain the signal queue
- Signal count in PostgreSQL updated in batches of 10 (reduces write amplification)
- Redis sorted set for O(log N) priority-ordered dashboard reads
- MongoDB indexed on `work_item_id` and `timestamp` for fast signal lookups
- `selectinload` used for ORM relationships (avoids N+1 queries)

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | postgres://... | PostgreSQL async DSN |
| `MONGODB_URL` | mongodb://... | MongoDB connection string |
| `REDIS_URL` | redis://localhost:6379/0 | Redis DSN |
| `SIGNAL_BUFFER_SIZE` | 50000 | Max in-memory queue depth |
| `DEBOUNCE_WINDOW_SECONDS` | 10 | Dedup window per component |
| `DEBOUNCE_THRESHOLD` | 100 | Signals per window before new WI |
| `SIGNAL_WORKER_CONCURRENCY` | 8 | Worker coroutine count |
| `METRICS_INTERVAL_SECONDS` | 5 | Console throughput print interval |
| `RATE_LIMIT_PER_SECOND` | 15000 | Max ingestion rate |
| `API_KEY` | ims-dev-key-... | Optional API authentication |

---

## Project Structure

```
ims/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── signals.py        # Ingestion REST + WebSocket endpoints
│   │   │   ├── work_items.py     # CRUD + transitions + RCA endpoints
│   │   │   └── dashboard.py      # Stats + health endpoints
│   │   ├── core/
│   │   │   └── config.py         # Pydantic settings
│   │   ├── db/
│   │   │   └── connections.py    # PG + MongoDB + Redis connection managers
│   │   ├── models/
│   │   │   ├── orm.py            # SQLAlchemy ORM models
│   │   │   └── schemas.py        # Pydantic v2 request/response schemas
│   │   ├── services/
│   │   │   ├── alert_strategy.py # Strategy pattern for alert priority
│   │   │   └── state_machine.py  # State pattern for work item lifecycle
│   │   ├── workers/
│   │   │   └── signal_processor.py # Async worker pool + debounce engine
│   │   └── main.py               # FastAPI app factory + lifecycle
│   ├── tests/
│   │   └── test_rca_and_state.py # Unit tests
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx     # Live stats + active incidents
│   │   │   ├── WorkItems.jsx     # Filterable incident list
│   │   │   ├── IncidentDetail.jsx# Detail + RCA form + timeline
│   │   │   └── IngestDemo.jsx    # Signal injection + burst tester
│   │   ├── services/
│   │   │   └── api.js            # Typed API client
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   └── styles.css
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
├── scripts/
│   ├── init_postgres.sql         # Schema + indexes + triggers
│   ├── mock_failure.py           # Cascading failure simulator
│   └── sample_failure_event.json # Sample payload reference
└── docker-compose.yml
```

---

## Incident Lifecycle

```
Signal arrives
     │
     ▼
Rate Limiter → 429 if exceeded
     │
     ▼
asyncio.Queue.put_nowait() → dropped=1 if full
     │
     ▼
Worker picks up signal
     │
     ├──► MongoDB: raw signal stored (Data Lake)
     │
     └──► Debounce check:
              │
              ├── Window active for component_id?
              │       └── YES → increment counter, link signal_id in Mongo
              │
              └── NO / expired?
                      └── Alert Strategy → priority/channel
                          PostgreSQL: WorkItem created (ACID)
                          Redis: hot-path cache updated
```

---

## MTTR Calculation

MTTR is calculated automatically when a Work Item transitions to `CLOSED`:

```
MTTR = closed_time − start_time (first signal timestamp)
```

Stored as `mttr_seconds` (float) on the `work_items` table. Aggregated average is exposed via `/api/v1/dashboard/stats`.
