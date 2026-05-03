"""
Pydantic v2 schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.orm import ComponentType, PriorityLevel, WorkItemStatus


# ── Signal Ingestion ───────────────────────────────────────────────────────────

class SignalPayload(BaseModel):
    """Raw signal from monitored infrastructure component."""
    component_id: str = Field(..., min_length=1, max_length=255, examples=["CACHE_CLUSTER_01"])
    component_type: ComponentType = ComponentType.UNKNOWN
    error_code: Optional[str] = None
    message: str = Field(..., min_length=1)
    severity: str = Field(default="ERROR", pattern="^(DEBUG|INFO|WARN|ERROR|CRITICAL)$")
    latency_ms: Optional[float] = Field(default=None, ge=0)
    metadata: Optional[Dict[str, Any]] = None
    source_host: Optional[str] = None
    timestamp: Optional[datetime] = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def default_timestamp(cls, v):
        return v or datetime.utcnow()


class SignalBatch(BaseModel):
    signals: List[SignalPayload] = Field(..., min_length=1, max_length=500)


class SignalIngestionResponse(BaseModel):
    accepted: int
    queued: int
    dropped: int
    message: str


# ── Work Items ─────────────────────────────────────────────────────────────────

class WorkItemResponse(BaseModel):
    id: UUID
    component_id: str
    component_type: ComponentType
    priority: PriorityLevel
    status: WorkItemStatus
    title: str
    signal_count: int
    start_time: datetime
    resolved_time: Optional[datetime]
    closed_time: Optional[datetime]
    mttr_seconds: Optional[float]
    assignee: Optional[str]
    created_at: datetime
    updated_at: datetime
    has_rca: bool = False

    model_config = {"from_attributes": True}


class WorkItemListResponse(BaseModel):
    items: List[WorkItemResponse]
    total: int
    page: int
    page_size: int


class StatusTransitionRequest(BaseModel):
    new_status: WorkItemStatus
    notes: Optional[str] = None
    transitioned_by: str = "user"


class AssignRequest(BaseModel):
    assignee: str = Field(..., min_length=1)


# ── RCA ────────────────────────────────────────────────────────────────────────

RCA_CATEGORIES = [
    "Infrastructure Failure",
    "Software Bug",
    "Configuration Error",
    "Capacity Issue",
    "Network Issue",
    "Human Error",
    "Third Party",
    "Unknown",
]


class RCACreateRequest(BaseModel):
    incident_start: datetime
    incident_end: datetime
    root_cause_category: str
    root_cause_detail: str = Field(..., min_length=10)
    fix_applied: str = Field(..., min_length=10)
    prevention_steps: str = Field(..., min_length=10)
    impact_summary: Optional[str] = None
    created_by: str = "user"

    @field_validator("root_cause_category")
    @classmethod
    def validate_category(cls, v):
        if v not in RCA_CATEGORIES:
            raise ValueError(f"Must be one of: {RCA_CATEGORIES}")
        return v

    @field_validator("incident_end")
    @classmethod
    def end_after_start(cls, v, info):
        if "incident_start" in info.data and v <= info.data["incident_start"]:
            raise ValueError("incident_end must be after incident_start")
        return v


class RCAResponse(BaseModel):
    id: UUID
    work_item_id: UUID
    incident_start: datetime
    incident_end: datetime
    root_cause_category: str
    root_cause_detail: str
    fix_applied: str
    prevention_steps: str
    impact_summary: Optional[str]
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Dashboard ──────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_open: int
    total_investigating: int
    total_resolved: int
    total_closed_today: int
    p0_active: int
    p1_active: int
    avg_mttr_seconds: Optional[float]
    signals_last_hour: int


class HealthResponse(BaseModel):
    status: str
    postgres: str
    mongodb: str
    redis: str
    buffer_depth: int
    uptime_seconds: float
    version: str = "1.0.0"
