"""
Unit tests — RCA validation logic + State machine transitions.
Run with: pytest backend/tests/ -v
"""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ── RCA Schema validation ──────────────────────────────────────────────────────

from app.models.schemas import RCACreateRequest


class TestRCAValidation:
    """Tests for RCA create request validation."""

    def _valid_payload(self) -> dict:
        base = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
        return {
            "incident_start": base,
            "incident_end": base + timedelta(hours=2),
            "root_cause_category": "Infrastructure Failure",
            "root_cause_detail": "Primary DB node ran out of disk space due to unrotated logs.",
            "fix_applied": "Cleared old WAL logs and expanded volume by 100GB.",
            "prevention_steps": "Implement automated log rotation and disk usage alerting.",
            "impact_summary": "Full write outage for 2 hours affecting all services.",
        }

    def test_valid_rca_passes(self):
        rca = RCACreateRequest(**self._valid_payload())
        assert rca.root_cause_category == "Infrastructure Failure"

    def test_invalid_category_raises(self):
        data = self._valid_payload()
        data["root_cause_category"] = "Alien Invasion"
        with pytest.raises(Exception):
            RCACreateRequest(**data)

    def test_end_before_start_raises(self):
        data = self._valid_payload()
        data["incident_end"] = data["incident_start"] - timedelta(hours=1)
        with pytest.raises(Exception):
            RCACreateRequest(**data)

    def test_end_equal_start_raises(self):
        data = self._valid_payload()
        data["incident_end"] = data["incident_start"]
        with pytest.raises(Exception):
            RCACreateRequest(**data)

    def test_short_fix_applied_raises(self):
        data = self._valid_payload()
        data["fix_applied"] = "Fixed"  # < 10 chars
        with pytest.raises(Exception):
            RCACreateRequest(**data)

    def test_short_prevention_steps_raises(self):
        data = self._valid_payload()
        data["prevention_steps"] = "Monitor"  # < 10 chars
        with pytest.raises(Exception):
            RCACreateRequest(**data)

    def test_short_root_cause_detail_raises(self):
        data = self._valid_payload()
        data["root_cause_detail"] = "Unknown"  # < 10 chars
        with pytest.raises(Exception):
            RCACreateRequest(**data)

    def test_all_valid_categories(self):
        valid = [
            "Infrastructure Failure", "Software Bug", "Configuration Error",
            "Capacity Issue", "Network Issue", "Human Error", "Third Party", "Unknown"
        ]
        for cat in valid:
            data = self._valid_payload()
            data["root_cause_category"] = cat
            rca = RCACreateRequest(**data)
            assert rca.root_cause_category == cat


# ── Alert Strategy ─────────────────────────────────────────────────────────────

from app.models.orm import ComponentType, PriorityLevel
from app.services.alert_strategy import evaluate_alert, get_alert_strategy


class TestAlertStrategy:
    def test_rdbms_is_p0(self):
        ctx = evaluate_alert("DB_01", ComponentType.RDBMS, "Connection refused")
        assert ctx.priority == PriorityLevel.P0
        assert ctx.escalate is True
        assert ctx.channel == "pagerduty"

    def test_cache_is_p2(self):
        ctx = evaluate_alert("CACHE_01", ComponentType.CACHE, "Cache miss rate 90%")
        assert ctx.priority == PriorityLevel.P2
        assert ctx.escalate is False
        assert ctx.channel == "slack"

    def test_mcp_host_is_p0(self):
        ctx = evaluate_alert("MCP_01", ComponentType.MCP_HOST, "Host unreachable")
        assert ctx.priority == PriorityLevel.P0
        assert ctx.escalate is True

    def test_async_queue_is_p1(self):
        ctx = evaluate_alert("QUEUE_01", ComponentType.ASYNC_QUEUE, "Consumer lag 50k")
        assert ctx.priority == PriorityLevel.P1

    def test_api_is_p1(self):
        ctx = evaluate_alert("API_01", ComponentType.API, "500 errors spiking")
        assert ctx.priority == PriorityLevel.P1

    def test_unknown_is_p3(self):
        ctx = evaluate_alert("UNKNOWN_01", ComponentType.UNKNOWN, "mystery error")
        assert ctx.priority == PriorityLevel.P3


# ── State Machine ──────────────────────────────────────────────────────────────

from app.services.state_machine import (
    InvalidTransitionError,
    RCAMissingError,
    WorkItemContext,
)


def _mock_work_item(status):
    """Create a minimal mock WorkItem."""
    wi = MagicMock()
    wi.id = uuid4()
    wi.status = status
    wi.start_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    wi.resolved_time = None
    wi.closed_time = None
    wi.mttr_seconds = None
    return wi


class TestStateMachine:
    @pytest.mark.asyncio
    async def test_open_to_investigating(self):
        from app.models.orm import WorkItemStatus
        wi = _mock_work_item(WorkItemStatus.OPEN)
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        session.add = MagicMock()
        session.flush = AsyncMock()

        ctx = WorkItemContext(wi, session)
        await ctx.transition(WorkItemStatus.INVESTIGATING)
        assert wi.status == WorkItemStatus.INVESTIGATING

    @pytest.mark.asyncio
    async def test_open_cannot_go_to_closed(self):
        from app.models.orm import WorkItemStatus
        wi = _mock_work_item(WorkItemStatus.OPEN)
        session = AsyncMock()
        ctx = WorkItemContext(wi, session)
        with pytest.raises(InvalidTransitionError):
            await ctx.transition(WorkItemStatus.CLOSED)

    @pytest.mark.asyncio
    async def test_closed_is_terminal(self):
        from app.models.orm import WorkItemStatus
        wi = _mock_work_item(WorkItemStatus.CLOSED)
        session = AsyncMock()
        ctx = WorkItemContext(wi, session)
        with pytest.raises(InvalidTransitionError):
            await ctx.transition(WorkItemStatus.OPEN)

    @pytest.mark.asyncio
    async def test_resolved_to_closed_requires_rca(self):
        from app.models.orm import WorkItemStatus
        wi = _mock_work_item(WorkItemStatus.RESOLVED)
        session = AsyncMock()
        # No RCA found
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        session.add = MagicMock()
        session.flush = AsyncMock()

        ctx = WorkItemContext(wi, session)
        with pytest.raises(RCAMissingError):
            await ctx.transition(WorkItemStatus.CLOSED)

    @pytest.mark.asyncio
    async def test_resolved_to_closed_with_valid_rca(self):
        from app.models.orm import WorkItemStatus
        wi = _mock_work_item(WorkItemStatus.RESOLVED)

        mock_rca = MagicMock()
        mock_rca.root_cause_detail = "Primary DB node ran out of disk — caused by log buildup"
        mock_rca.fix_applied = "Cleared WAL logs and provisioned additional storage"
        mock_rca.prevention_steps = "Set up automated log rotation and disk monitoring"

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: mock_rca))
        session.add = MagicMock()
        session.flush = AsyncMock()

        ctx = WorkItemContext(wi, session)
        await ctx.transition(WorkItemStatus.CLOSED)
        assert wi.status == WorkItemStatus.CLOSED
        assert wi.mttr_seconds is not None
