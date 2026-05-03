"""
Alerting Strategy Pattern.
━━━━━━━━━━━━━━━━━━━━━━━━━
Uses the STRATEGY design pattern to determine alert priority and
notification channel based on the failing component type.

  ComponentType ──► AlertStrategy ──► AlertContext.execute()

New strategies can be plugged in without changing calling code.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Dict, Type

import structlog

from app.models.orm import ComponentType, PriorityLevel

log = structlog.get_logger()


@dataclass
class AlertContext:
    """Output from an alert strategy evaluation."""
    priority: PriorityLevel
    channel: str           # e.g. "pagerduty", "slack", "email"
    escalate: bool         # Should this page on-call immediately?
    message: str


# ── Abstract Strategy ──────────────────────────────────────────────────────────

class AlertStrategy(abc.ABC):
    @abc.abstractmethod
    def evaluate(self, component_id: str, error_message: str) -> AlertContext:
        """Return alert context for the given signal."""


# ── Concrete Strategies ────────────────────────────────────────────────────────

class RDBMSAlertStrategy(AlertStrategy):
    """Database failures are P0 — highest severity, immediate page."""

    def evaluate(self, component_id: str, error_message: str) -> AlertContext:
        return AlertContext(
            priority=PriorityLevel.P0,
            channel="pagerduty",
            escalate=True,
            message=f"🔴 P0 RDBMS FAILURE on {component_id}: {error_message[:120]}",
        )


class CacheAlertStrategy(AlertStrategy):
    """Cache failures degrade performance but don't cause data loss → P2."""

    def evaluate(self, component_id: str, error_message: str) -> AlertContext:
        return AlertContext(
            priority=PriorityLevel.P2,
            channel="slack",
            escalate=False,
            message=f"🟡 P2 Cache degradation on {component_id}: {error_message[:120]}",
        )


class AsyncQueueAlertStrategy(AlertStrategy):
    """Queue failures can cause data loss if consumers fall behind → P1."""

    def evaluate(self, component_id: str, error_message: str) -> AlertContext:
        return AlertContext(
            priority=PriorityLevel.P1,
            channel="pagerduty",
            escalate=True,
            message=f"🟠 P1 Async Queue failure on {component_id}: {error_message[:120]}",
        )


class APIAlertStrategy(AlertStrategy):
    """API failures affect end users directly → P1."""

    def evaluate(self, component_id: str, error_message: str) -> AlertContext:
        return AlertContext(
            priority=PriorityLevel.P1,
            channel="slack",
            escalate=False,
            message=f"🟠 P1 API error on {component_id}: {error_message[:120]}",
        )


class MCPHostAlertStrategy(AlertStrategy):
    """MCP Host failures block entire service mesh → P0."""

    def evaluate(self, component_id: str, error_message: str) -> AlertContext:
        return AlertContext(
            priority=PriorityLevel.P0,
            channel="pagerduty",
            escalate=True,
            message=f"🔴 P0 MCP Host unreachable {component_id}: {error_message[:120]}",
        )


class NoSQLAlertStrategy(AlertStrategy):
    """NoSQL failures affect reads/writes → P1."""

    def evaluate(self, component_id: str, error_message: str) -> AlertContext:
        return AlertContext(
            priority=PriorityLevel.P1,
            channel="slack",
            escalate=False,
            message=f"🟠 P1 NoSQL issue on {component_id}: {error_message[:120]}",
        )


class DefaultAlertStrategy(AlertStrategy):
    """Fallback for unknown component types → P3."""

    def evaluate(self, component_id: str, error_message: str) -> AlertContext:
        return AlertContext(
            priority=PriorityLevel.P3,
            channel="email",
            escalate=False,
            message=f"ℹ️ P3 Unknown component {component_id}: {error_message[:120]}",
        )


# ── Strategy Registry / Factory ────────────────────────────────────────────────

_STRATEGY_MAP: Dict[ComponentType, Type[AlertStrategy]] = {
    ComponentType.RDBMS: RDBMSAlertStrategy,
    ComponentType.CACHE: CacheAlertStrategy,
    ComponentType.ASYNC_QUEUE: AsyncQueueAlertStrategy,
    ComponentType.API: APIAlertStrategy,
    ComponentType.MCP_HOST: MCPHostAlertStrategy,
    ComponentType.NOSQL: NoSQLAlertStrategy,
}


def get_alert_strategy(component_type: ComponentType) -> AlertStrategy:
    """Factory: returns the right strategy for a component type."""
    strategy_cls = _STRATEGY_MAP.get(component_type, DefaultAlertStrategy)
    return strategy_cls()


def evaluate_alert(
    component_id: str,
    component_type: ComponentType,
    error_message: str,
) -> AlertContext:
    """Convenience wrapper — evaluates strategy and logs result."""
    strategy = get_alert_strategy(component_type)
    ctx = strategy.evaluate(component_id, error_message)
    log.info(
        "alert_evaluated",
        component_id=component_id,
        component_type=component_type,
        priority=ctx.priority,
        channel=ctx.channel,
        escalate=ctx.escalate,
    )
    return ctx
