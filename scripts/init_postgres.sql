-- IMS PostgreSQL Schema
-- Source of Truth: Work Items + RCA

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Work Item states enum
CREATE TYPE work_item_status AS ENUM ('OPEN', 'INVESTIGATING', 'RESOLVED', 'CLOSED');

-- Component severity enum
CREATE TYPE component_type AS ENUM (
  'RDBMS', 'NOSQL', 'CACHE', 'ASYNC_QUEUE', 'API', 'MCP_HOST', 'UNKNOWN'
);

CREATE TYPE priority_level AS ENUM ('P0', 'P1', 'P2', 'P3');

-- Work Items table
CREATE TABLE work_items (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  component_id    TEXT NOT NULL,
  component_type  component_type NOT NULL DEFAULT 'UNKNOWN',
  priority        priority_level NOT NULL,
  status          work_item_status NOT NULL DEFAULT 'OPEN',
  title           TEXT NOT NULL,
  signal_count    INTEGER NOT NULL DEFAULT 1,
  start_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_time   TIMESTAMPTZ,
  closed_time     TIMESTAMPTZ,
  mttr_seconds    DOUBLE PRECISION,
  assignee        TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- RCA table (1-to-1 with work_items)
CREATE TABLE rca_records (
  id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  work_item_id        UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  incident_start      TIMESTAMPTZ NOT NULL,
  incident_end        TIMESTAMPTZ NOT NULL,
  root_cause_category TEXT NOT NULL CHECK (root_cause_category IN (
    'Infrastructure Failure', 'Software Bug', 'Configuration Error',
    'Capacity Issue', 'Network Issue', 'Human Error', 'Third Party', 'Unknown'
  )),
  root_cause_detail   TEXT NOT NULL,
  fix_applied         TEXT NOT NULL,
  prevention_steps    TEXT NOT NULL,
  impact_summary      TEXT,
  created_by          TEXT NOT NULL DEFAULT 'system',
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT unique_rca_per_workitem UNIQUE(work_item_id)
);

-- Status transition audit log
CREATE TABLE status_transitions (
  id            BIGSERIAL PRIMARY KEY,
  work_item_id  UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  from_status   work_item_status,
  to_status     work_item_status NOT NULL,
  transitioned_by TEXT NOT NULL DEFAULT 'system',
  notes         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Timeseries aggregations for signal throughput
CREATE TABLE signal_metrics (
  bucket          TIMESTAMPTZ NOT NULL,
  component_id    TEXT NOT NULL,
  component_type  component_type NOT NULL,
  signal_count    BIGINT NOT NULL DEFAULT 0,
  error_rate      DOUBLE PRECISION,
  avg_latency_ms  DOUBLE PRECISION,
  PRIMARY KEY (bucket, component_id)
);

-- Indexes for performance
CREATE INDEX idx_work_items_status ON work_items(status);
CREATE INDEX idx_work_items_component ON work_items(component_id);
CREATE INDEX idx_work_items_priority ON work_items(priority);
CREATE INDEX idx_work_items_created ON work_items(created_at DESC);
CREATE INDEX idx_status_transitions_workitem ON status_transitions(work_item_id);
CREATE INDEX idx_signal_metrics_bucket ON signal_metrics(bucket DESC);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_work_items_updated_at
  BEFORE UPDATE ON work_items
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
