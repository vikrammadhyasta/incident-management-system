"""
SQLAlchemy ORM models for PostgreSQL (Source of Truth).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.connections import Base


class WorkItemStatus(str, enum.Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ComponentType(str, enum.Enum):
    RDBMS = "RDBMS"
    NOSQL = "NOSQL"
    CACHE = "CACHE"
    ASYNC_QUEUE = "ASYNC_QUEUE"
    API = "API"
    MCP_HOST = "MCP_HOST"
    UNKNOWN = "UNKNOWN"


class PriorityLevel(str, enum.Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class WorkItem(Base):
    __tablename__ = "work_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id = Column(String(255), nullable=False, index=True)
    component_type = Column(
        Enum(ComponentType, name="component_type"),
        nullable=False,
        default=ComponentType.UNKNOWN,
    )
    priority = Column(Enum(PriorityLevel, name="priority_level"), nullable=False)
    status = Column(
        Enum(WorkItemStatus, name="work_item_status"),
        nullable=False,
        default=WorkItemStatus.OPEN,
    )
    title = Column(Text, nullable=False)
    signal_count = Column(Integer, nullable=False, default=1)
    start_time = Column(DateTime(timezone=True), nullable=False, default=func.now())
    resolved_time = Column(DateTime(timezone=True))
    closed_time = Column(DateTime(timezone=True))
    mttr_seconds = Column(Double)
    assignee = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    rca = relationship("RCARecord", back_populates="work_item", uselist=False, cascade="all, delete-orphan")
    transitions = relationship("StatusTransition", back_populates="work_item", cascade="all, delete-orphan")


class RCARecord(Base):
    __tablename__ = "rca_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, unique=True)
    incident_start = Column(DateTime(timezone=True), nullable=False)
    incident_end = Column(DateTime(timezone=True), nullable=False)
    root_cause_category = Column(String(100), nullable=False)
    root_cause_detail = Column(Text, nullable=False)
    fix_applied = Column(Text, nullable=False)
    prevention_steps = Column(Text, nullable=False)
    impact_summary = Column(Text)
    created_by = Column(String(255), nullable=False, default="system")
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    work_item = relationship("WorkItem", back_populates="rca")


class StatusTransition(Base):
    __tablename__ = "status_transitions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    work_item_id = Column(UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    from_status = Column(Enum(WorkItemStatus, name="work_item_status"))
    to_status = Column(Enum(WorkItemStatus, name="work_item_status"), nullable=False)
    transitioned_by = Column(String(255), nullable=False, default="system")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    work_item = relationship("WorkItem", back_populates="transitions")
