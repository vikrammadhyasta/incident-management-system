"""
Work Item State Machine — STATE design pattern.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each state is a class that knows which transitions are valid.
The WorkItemContext delegates transition logic to the current state.

  OPEN → INVESTIGATING → RESOLVED → CLOSED
                ↑___________↑  (can re-open back to INVESTIGATING)

CLOSED requires a complete RCA — enforced at the state level.
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import RCARecord, StatusTransition, WorkItem, WorkItemStatus

log = structlog.get_logger()


# ── Abstract State ─────────────────────────────────────────────────────────────

class WorkItemState(abc.ABC):
    status: WorkItemStatus

    async def transition_to(
        self,
        context: "WorkItemContext",
        new_status: WorkItemStatus,
        notes: Optional[str] = None,
        actor: str = "system",
    ) -> None:
        raise InvalidTransitionError(
            f"Cannot transition from {self.status} → {new_status}"
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"


# ── Concrete States ────────────────────────────────────────────────────────────

class OpenState(WorkItemState):
    status = WorkItemStatus.OPEN

    async def transition_to(self, context, new_status, notes=None, actor="system"):
        if new_status == WorkItemStatus.INVESTIGATING:
            await context._apply_transition(new_status, notes, actor)
        else:
            await super().transition_to(context, new_status, notes, actor)


class InvestigatingState(WorkItemState):
    status = WorkItemStatus.INVESTIGATING

    async def transition_to(self, context, new_status, notes=None, actor="system"):
        if new_status in (WorkItemStatus.RESOLVED, WorkItemStatus.OPEN):
            await context._apply_transition(new_status, notes, actor)
        else:
            await super().transition_to(context, new_status, notes, actor)


class ResolvedState(WorkItemState):
    status = WorkItemStatus.RESOLVED

    async def transition_to(self, context, new_status, notes=None, actor="system"):
        if new_status == WorkItemStatus.CLOSED:
            # Guard: RCA must exist and be complete
            await context._assert_rca_complete()
            await context._apply_transition(new_status, notes, actor)
        elif new_status == WorkItemStatus.INVESTIGATING:
            # Allow re-opening if regression discovered
            await context._apply_transition(new_status, notes, actor)
        else:
            await super().transition_to(context, new_status, notes, actor)


class ClosedState(WorkItemState):
    status = WorkItemStatus.CLOSED

    async def transition_to(self, context, new_status, notes=None, actor="system"):
        # Terminal state — no transitions allowed
        raise InvalidTransitionError("Work item is CLOSED. Create a new incident.")


# ── State Registry ─────────────────────────────────────────────────────────────

_STATE_MAP: dict[WorkItemStatus, WorkItemState] = {
    WorkItemStatus.OPEN: OpenState(),
    WorkItemStatus.INVESTIGATING: InvestigatingState(),
    WorkItemStatus.RESOLVED: ResolvedState(),
    WorkItemStatus.CLOSED: ClosedState(),
}


# ── Context ────────────────────────────────────────────────────────────────────

class WorkItemContext:
    """
    Holds a reference to the current state and delegates
    all transition logic to the state object.
    """

    def __init__(self, work_item: WorkItem, session: AsyncSession):
        self._work_item = work_item
        self._session = session
        self._state: WorkItemState = _STATE_MAP[work_item.status]

    async def transition(
        self,
        new_status: WorkItemStatus,
        notes: Optional[str] = None,
        actor: str = "system",
    ) -> WorkItem:
        log.info(
            "state_transition_requested",
            work_item_id=str(self._work_item.id),
            from_status=self._state.status,
            to_status=new_status,
            actor=actor,
        )
        await self._state.transition_to(self, new_status, notes, actor)
        return self._work_item

    # ── Internal helpers (called by state objects) ─────────────────────────────

    async def _apply_transition(
        self,
        new_status: WorkItemStatus,
        notes: Optional[str],
        actor: str,
    ) -> None:
        from_status = self._work_item.status
        now = datetime.now(timezone.utc)

        # Persist audit log
        transition = StatusTransition(
            work_item_id=self._work_item.id,
            from_status=from_status,
            to_status=new_status,
            transitioned_by=actor,
            notes=notes,
        )
        self._session.add(transition)

        # Update work item
        self._work_item.status = new_status
        if new_status == WorkItemStatus.RESOLVED:
            self._work_item.resolved_time = now
        elif new_status == WorkItemStatus.CLOSED:
            self._work_item.closed_time = now
            # Calculate MTTR
            if self._work_item.start_time:
                delta = now - self._work_item.start_time.replace(tzinfo=timezone.utc)
                self._work_item.mttr_seconds = delta.total_seconds()

        await self._session.flush()

        # Advance internal state
        self._state = _STATE_MAP[new_status]
        log.info(
            "state_transition_applied",
            work_item_id=str(self._work_item.id),
            from_status=from_status,
            to_status=new_status,
        )

    async def _assert_rca_complete(self) -> None:
        """Raises RCAMissingError if RCA is absent or incomplete."""
        result = await self._session.execute(
            select(RCARecord).where(RCARecord.work_item_id == self._work_item.id)
        )
        rca = result.scalar_one_or_none()
        if rca is None:
            raise RCAMissingError(
                "RCA is required before closing a work item. "
                "Please submit a complete Root Cause Analysis."
            )
        # Validate required fields are non-empty
        required = [rca.root_cause_detail, rca.fix_applied, rca.prevention_steps]
        if any(not field or len(field.strip()) < 10 for field in required):
            raise RCAIncompleteError(
                "RCA fields (root_cause_detail, fix_applied, prevention_steps) "
                "must each be at least 10 characters."
            )


# ── Custom Exceptions ──────────────────────────────────────────────────────────

class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""


class RCAMissingError(Exception):
    """Raised when CLOSED is attempted without an RCA."""


class RCAIncompleteError(Exception):
    """Raised when RCA exists but has incomplete fields."""
