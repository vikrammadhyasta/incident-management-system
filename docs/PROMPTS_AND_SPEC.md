# Prompts, Spec & Planning Notes

> This file documents the AI-assisted development process, prompts used, and design decisions made during the build.
> Checked in as required by submission guidelines.

---

## Initial System Analysis Prompt

```
Assignment: Build a Mission-Critical Incident Management System (IMS) for Zeotap SRE Intern role.

Requirements:
- High-throughput signal ingestion (10,000 signals/sec bursts)
- Debounce: 100 signals for same component_id within 10s → 1 WorkItem
- Three storage tiers: PostgreSQL (source of truth), MongoDB (data lake), Redis (hot-path cache)
- Strategy pattern for alerting (P0 for RDBMS, P2 for Cache, etc.)
- State pattern for WorkItem lifecycle (OPEN → INVESTIGATING → RESOLVED → CLOSED)
- Mandatory RCA before CLOSED transition
- MTTR calculation
- React dashboard with live feed, incident detail, RCA form
- Docker Compose for one-command setup
- Unit tests for RCA validation and state transitions
```

---

## Architecture Decision Process

### Storage Tier Selection
**Prompt used**: "Given the requirement for: (a) raw signal storage at high volume with flexible schema, 
(b) structured WorkItem records needing ACID transactions, (c) sub-millisecond dashboard reads —
what is the optimal three-tier storage architecture?"

**Decision**: MongoDB (Data Lake) + PostgreSQL (Source of Truth) + Redis (Hot-Path)

**Rationale documented in**: `docs/ARCHITECTURE.md`

---

## Design Pattern Selection

### Why Strategy for Alerting?
The problem says "different component failures require different alert types". This is the textbook use case for Strategy — the algorithm (alerting logic) varies independently from the context that uses it. Adding a new component type requires only a new strategy class.

### Why State for WorkItem lifecycle?
The lifecycle is a finite state machine with strict rules:
- OPEN can only go to INVESTIGATING
- RESOLVED can go to CLOSED (only with RCA) or back to INVESTIGATING
- CLOSED is terminal

State pattern makes each transition rule local to the state that owns it, rather than scattered across if/elif chains.

---

## Backpressure Design

**Key insight**: The ingestion API must NEVER block, even when the persistence layer is slow.

```
Pattern chosen: Producer-Consumer with bounded queue

Producer (HTTP handler):
  - put_nowait() → non-blocking
  - Returns dropped=N immediately if full

Consumer (8 async workers):
  - get() → blocks until work available
  - Processes one signal at a time
  - Error in one signal doesn't stop other workers
```

**Queue size of 50,000**: At 10,000 signals/sec burst, this gives 5 seconds of buffer. 
If MongoDB write latency is under 5 seconds average, the queue never fills.

---

## Schema Design Decisions

### PostgreSQL
- `work_items`: UUID primary keys (globally unique, no sharding conflicts)
- `status_transitions`: Append-only audit log — never updated, only inserted
- `rca_records`: UNIQUE constraint on `work_item_id` enforces 1 RCA per incident
- `updated_at` trigger: Automatic timestamp management

### MongoDB Signal Document
```json
{
  "_id": ObjectId,
  "component_id": "CACHE_CLUSTER_01",
  "component_type": "CACHE",
  "message": "...",
  "severity": "ERROR",
  "work_item_id": "uuid-string",   ← linked after debounce
  "timestamp": ISODate,
  "ingested_at": ISODate
}
```

Indexed on `work_item_id` + `timestamp` for efficient signal lookups per incident.

---

## Testing Strategy

**Unit tests focus on business logic, not infrastructure**:

1. `TestRCAValidation` — Tests Pydantic schema validation. No DB needed.
   - All 8 valid categories pass
   - Invalid category raises ValidationError
   - end < start raises ValidationError
   - Short fields (< 10 chars) raise ValidationError

2. `TestAlertStrategy` — Tests strategy selection and output.
   - Each component type maps to correct priority
   - RDBMS → P0, CACHE → P2, ASYNC_QUEUE → P1, etc.

3. `TestStateMachine` — Tests state transitions using mocks.
   - Valid transitions succeed
   - Invalid transitions raise InvalidTransitionError
   - CLOSED without RCA raises RCAMissingError
   - CLOSED with complete RCA succeeds + calculates MTTR

**Mocking approach**: `AsyncMock` for DB sessions avoids needing a live database for unit tests.

---

## Frontend Design Decisions

**Dashboard auto-refresh**: 10-second polling (simple, reliable). WebSocket could be added for push-based updates.

**Redis fast path**: Dashboard `/active` endpoint reads from Redis sorted set first (sub-ms). Falls back to PostgreSQL if Redis is unavailable.

**Signal Injector page**: Added as a bonus — allows manual testing of debounce logic without running the Python script. Burst tester shows exactly how many signals become how many WorkItems.

---

## Bonus Features Added

1. **WebSocket ingestion** (`/api/v1/signals/ws/ingest`) — for streaming producers
2. **Signal Injector UI** — interactive burst tester in the dashboard
3. **Status transition timeline** — full audit trail per incident
4. **API Key authentication** — optional header, configurable via env var
5. **Throughput metrics endpoint** — `/api/v1/signals/metrics` for ops visibility
6. **Structured logging** — `structlog` for JSON-formatted logs
7. **Row-level locking** — `SELECT FOR UPDATE` prevents concurrent transition races
8. **Graceful shutdown** — queue drain on SIGTERM
