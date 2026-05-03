"""
Work Items API — /api/v1/work-items
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRUD + state transitions + RCA management.
All state transitions go through the WorkItemContext (State pattern).
"""

from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.connections import get_db_session, get_mongo_db, get_redis
from app.models.orm import RCARecord, StatusTransition, WorkItem, WorkItemStatus
from app.models.schemas import (
    AssignRequest,
    RCACreateRequest,
    RCAResponse,
    StatusTransitionRequest,
    WorkItemListResponse,
    WorkItemResponse,
)
from app.services.state_machine import (
    InvalidTransitionError,
    RCAIncompleteError,
    RCAMissingError,
    WorkItemContext,
)

router = APIRouter(prefix="/api/v1/work-items", tags=["Work Items"])
log = structlog.get_logger()


def _to_response(wi: WorkItem) -> WorkItemResponse:
    return WorkItemResponse(
        id=wi.id,
        component_id=wi.component_id,
        component_type=wi.component_type,
        priority=wi.priority,
        status=wi.status,
        title=wi.title,
        signal_count=wi.signal_count,
        start_time=wi.start_time,
        resolved_time=wi.resolved_time,
        closed_time=wi.closed_time,
        mttr_seconds=wi.mttr_seconds,
        assignee=wi.assignee,
        created_at=wi.created_at,
        updated_at=wi.updated_at,
        has_rca=wi.rca is not None,
    )


@router.get("", response_model=WorkItemListResponse)
async def list_work_items(
    status: Optional[WorkItemStatus] = None,
    priority: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List work items with optional status/priority filtering, paginated."""
    async with get_db_session() as session:
        query = select(WorkItem).options(selectinload(WorkItem.rca))
        if status:
            query = query.where(WorkItem.status == status)
        if priority:
            query = query.where(WorkItem.priority == priority)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        query = (
            query
            .order_by(WorkItem.priority, WorkItem.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await session.execute(query)
        items = result.scalars().all()

    return WorkItemListResponse(
        items=[_to_response(wi) for wi in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{work_item_id}", response_model=WorkItemResponse)
async def get_work_item(work_item_id: UUID):
    async with get_db_session() as session:
        result = await session.execute(
            select(WorkItem)
            .options(selectinload(WorkItem.rca), selectinload(WorkItem.transitions))
            .where(WorkItem.id == work_item_id)
        )
        wi = result.scalar_one_or_none()
        if not wi:
            raise HTTPException(status_code=404, detail="Work item not found")
        return _to_response(wi)


@router.get("/{work_item_id}/signals")
async def get_work_item_signals(
    work_item_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """Fetch raw signals for a work item from MongoDB."""
    db = get_mongo_db()
    cursor = (
        db.signals
        .find({"work_item_id": str(work_item_id)})
        .sort("timestamp", -1)
        .skip(skip)
        .limit(limit)
    )
    signals = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        signals.append(doc)
    total = await db.signals.count_documents({"work_item_id": str(work_item_id)})
    return {"signals": signals, "total": total}


@router.post("/{work_item_id}/transition", response_model=WorkItemResponse)
async def transition_work_item(work_item_id: UUID, req: StatusTransitionRequest):
    """
    Transition a work item through its lifecycle.
    Enforced by the State machine — invalid transitions return 400.
    CLOSED transition requires a complete RCA — returns 422 if missing.
    """
    async with get_db_session() as session:
        result = await session.execute(
            select(WorkItem)
            .options(selectinload(WorkItem.rca))
            .where(WorkItem.id == work_item_id)
            .with_for_update()  # Row-level lock for safe concurrent transitions
        )
        wi = result.scalar_one_or_none()
        if not wi:
            raise HTTPException(status_code=404, detail="Work item not found")

        ctx = WorkItemContext(wi, session)
        try:
            await ctx.transition(req.new_status, req.notes, req.transitioned_by)
        except (RCAMissingError, RCAIncompleteError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )
        except InvalidTransitionError as e:
            raise HTTPException(status_code=400, detail=str(e))

        await session.refresh(wi, ["rca"])

        # Invalidate Redis cache
        try:
            r = await get_redis()
            await r.hset(f"wi:{work_item_id}", "status", req.new_status.value)
            if req.new_status in (WorkItemStatus.CLOSED, WorkItemStatus.RESOLVED):
                await r.zrem("active_incidents", str(work_item_id))
        except Exception:
            pass

        return _to_response(wi)


@router.post("/{work_item_id}/assign", response_model=WorkItemResponse)
async def assign_work_item(work_item_id: UUID, req: AssignRequest):
    async with get_db_session() as session:
        result = await session.execute(
            select(WorkItem).options(selectinload(WorkItem.rca)).where(WorkItem.id == work_item_id)
        )
        wi = result.scalar_one_or_none()
        if not wi:
            raise HTTPException(status_code=404, detail="Work item not found")
        wi.assignee = req.assignee
        await session.flush()
        return _to_response(wi)


# ── RCA endpoints ──────────────────────────────────────────────────────────────

@router.post("/{work_item_id}/rca", response_model=RCAResponse, status_code=201)
async def create_rca(work_item_id: UUID, req: RCACreateRequest):
    """Submit Root Cause Analysis for a work item."""
    async with get_db_session() as session:
        # Check work item exists
        wi_result = await session.execute(
            select(WorkItem).where(WorkItem.id == work_item_id)
        )
        wi = wi_result.scalar_one_or_none()
        if not wi:
            raise HTTPException(status_code=404, detail="Work item not found")

        # Check no duplicate RCA
        existing = await session.execute(
            select(RCARecord).where(RCARecord.work_item_id == work_item_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="RCA already exists for this work item")

        rca = RCARecord(
            work_item_id=work_item_id,
            incident_start=req.incident_start,
            incident_end=req.incident_end,
            root_cause_category=req.root_cause_category,
            root_cause_detail=req.root_cause_detail,
            fix_applied=req.fix_applied,
            prevention_steps=req.prevention_steps,
            impact_summary=req.impact_summary,
            created_by=req.created_by,
        )
        session.add(rca)
        await session.flush()
        return RCAResponse.model_validate(rca)


@router.get("/{work_item_id}/rca", response_model=RCAResponse)
async def get_rca(work_item_id: UUID):
    async with get_db_session() as session:
        result = await session.execute(
            select(RCARecord).where(RCARecord.work_item_id == work_item_id)
        )
        rca = result.scalar_one_or_none()
        if not rca:
            raise HTTPException(status_code=404, detail="No RCA found for this work item")
        return RCAResponse.model_validate(rca)


@router.get("/{work_item_id}/timeline")
async def get_timeline(work_item_id: UUID):
    """Return status transition audit log for a work item."""
    async with get_db_session() as session:
        result = await session.execute(
            select(StatusTransition)
            .where(StatusTransition.work_item_id == work_item_id)
            .order_by(StatusTransition.created_at)
        )
        transitions = result.scalars().all()
        return [
            {
                "from_status": t.from_status,
                "to_status": t.to_status,
                "transitioned_by": t.transitioned_by,
                "notes": t.notes,
                "timestamp": t.created_at.isoformat(),
            }
            for t in transitions
        ]
