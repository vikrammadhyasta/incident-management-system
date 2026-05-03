# Architecture & Design Decisions

## 1. Signal Ingestion — Why asyncio.Queue?

The bounded `asyncio.Queue` is the single most important design decision in the system. 

**Problem**: Ingestion API must handle 10,000 signals/sec bursts. If MongoDB or PostgreSQL are momentarily slow (e.g., during a high-load incident), a naive synchronous approach would cause the HTTP handlers to block, eventually exhausting the thread pool and crashing the API.

**Solution**: 
- HTTP handlers call `queue.put_nowait()` — **non-blocking, always returns immediately**
- If the queue is full (50,000 slots exhausted), signals are dropped and `dropped=N` is returned in the response
- 8 async worker coroutines drain the queue in parallel
- The HTTP layer is completely decoupled from the storage layer

**Why not Kafka/RabbitMQ?**
For this assignment's scope, an in-process bounded queue achieves the same backpressure semantics with zero infrastructure overhead. In production, we'd add Kafka between the API and workers for durability across restarts.

---

## 2. Debouncing — The 100-signals-per-10-seconds Rule

**Problem**: 100 signals for `CACHE_CLUSTER_01` within 10 seconds should create exactly 1 Work Item, not 100.

**Implementation**:
```python
_debounce_windows: Dict[str, DebounceWindow] = {}
_debounce_lock = asyncio.Lock()
```

Each unique `component_id` gets a `DebounceWindow` with:
- `work_item_id` (UUID pointing to the PostgreSQL row)
- `signal_ids` (list of MongoDB `_id` strings)
- `window_start` (monotonic timestamp)
- `count` (signals seen in this window)

When a signal arrives:
1. Lock acquired (prevents races across workers)
2. Check if window exists and hasn't expired (> 10 seconds)
3. **If expired**: Create new WorkItem in PostgreSQL → start new window
4. **If active**: Increment counter, link signal to existing WorkItem

Signal count in PostgreSQL is updated every 10 signals (batching) to avoid excessive writes.

---

## 3. Data Separation — Three Storage Tiers

| Store | What lives here | Why |
|-------|----------------|-----|
| **PostgreSQL** | WorkItems, RCA, StatusTransitions | ACID transactions, structured queries, foreign keys |
| **MongoDB** | Raw signal payloads | Schema-free, high write throughput, no joins needed |
| **Redis** | Active incident sorted set, WI hash cache | Sub-millisecond reads for dashboard, priority ordering |

This separation prevents the "one size fits all" anti-pattern. Raw signals (high-volume, schema-variable) would bloat a relational DB. Work Items (structured, transactional) don't belong in a document store.

---

## 4. Design Patterns

### Strategy Pattern (Alert Prioritization)
**Why**: Different component types have different blast radii. An RDBMS failure (P0) needs an immediate PagerDuty page. A cache degradation (P2) can go to Slack.

**How it works**: `get_alert_strategy(component_type)` returns the concrete strategy. Calling `.evaluate()` produces an `AlertContext`. Adding a new component type requires only a new class — no changes to the caller.

### State Pattern (Work Item Lifecycle)
**Why**: The lifecycle is a finite state machine with strict transition rules. Using `if/elif` chains would scatter the logic and make it easy to accidentally allow invalid transitions.

**How it works**: Each state class implements `transition_to()`. Invalid transitions raise `InvalidTransitionError`. `ResolvedState` guards the CLOSED transition by calling `_assert_rca_complete()` — this is where the mandatory RCA enforcement lives.

**Concurrency safety**: The transition endpoint uses `SELECT ... FOR UPDATE` (row-level lock in PostgreSQL) to prevent two concurrent requests from transitioning the same work item simultaneously.

---

## 5. MTTR Calculation

```
MTTR = closed_time − start_time
```

`start_time` is set to the first signal's timestamp when the WorkItem is created. `closed_time` is set in `_apply_transition()` when the state moves to CLOSED. The delta (in seconds) is stored as `mttr_seconds` on the row. The dashboard aggregates `AVG(mttr_seconds)` across all closed incidents.

---

## 6. Resilience Patterns

| Pattern | Where | What it does |
|---------|-------|-------------|
| Backpressure | asyncio.Queue | Drops signals instead of blocking |
| Circuit Breaker (soft) | Redis fallback | Dashboard reads from PG if Redis fails |
| Row-level locking | Status transitions | Prevents concurrent transition races |
| Pool pre-ping | SQLAlchemy | Auto-reconnects after transient PG failures |
| Graceful drain | Worker shutdown | Waits 10s for queue to empty before exiting |
| Retry-friendly API | All endpoints | Idempotent GETs; POST /ingest is safe to retry (signals get new Mongo IDs) |

---

## 7. Rate Limiting Strategy

Using `slowapi` (FastAPI wrapper around `limits` library):

- `/api/v1/signals/ingest` — 5,000 requests/minute per IP
- `/api/v1/signals/ingest/single` — 5,000 requests/minute per IP
- Returns HTTP 429 with Retry-After header when exceeded

In production, this would move to an API Gateway (Kong, AWS API Gateway) for distributed rate limiting across multiple backend instances.
