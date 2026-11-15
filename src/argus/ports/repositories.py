"""Hexagonal repository and event bus port interfaces for Argus."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from argus.core.schemas import (
    AgentSession,
    ArgusSpan,
    AuditLogEntry,
    AuditVerificationResult,
    CheckpointRecord,
    SessionStatus,
)
from argus.core.tenancy import TenantContext


@runtime_checkable
class TraceStore(Protocol):
    """Port for high-throughput columnar telemetry storage (ClickHouse in production)."""

    async def append_spans(self, ctx: TenantContext, spans: Sequence[ArgusSpan]) -> int:
        """Persist a batch of tenant-scoped spans and return the count written."""
        ...

    async def get_trace_subtree(
        self,
        ctx: TenantContext,
        root_dotted_order: str,
    ) -> list[ArgusSpan]:
        """Fetch an ordered trace subtree via lexicographical dotted_order prefix match."""
        ...

    async def get_session_spans(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[ArgusSpan]:
        """Fetch all spans belonging to a session ordered chronologically by dotted_order."""
        ...


@runtime_checkable
class ControlStore(Protocol):
    """Port for transactional control-plane entities and checkpoints (PostgreSQL in production)."""

    async def create_session(self, ctx: TenantContext, session: AgentSession) -> AgentSession:
        """Persist a new governed agent session."""
        ...

    async def get_session(self, ctx: TenantContext, session_id: uuid.UUID) -> AgentSession:
        """Retrieve a tenant-scoped session or raise EntityNotFoundError."""
        ...

    async def transition_session(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        expected_status: SessionStatus,
        next_status: SessionStatus,
    ) -> AgentSession:
        """Atomically transition session state, verifying current status and state machine rules."""
        ...

    async def save_checkpoint(
        self,
        ctx: TenantContext,
        checkpoint: CheckpointRecord,
        expected_parent_id: uuid.UUID | None,
    ) -> CheckpointRecord:
        """Persist a new checkpoint enforcing optimistic concurrency on expected_parent_id."""
        ...

    async def get_latest_checkpoint(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> CheckpointRecord | None:
        """Return the most recent checkpoint for a session, or None if none exist."""
        ...

    async def list_checkpoints(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[CheckpointRecord]:
        """Return all historical checkpoints for an agent session ordered chronologically."""
        ...

    async def list_sessions(
        self,
        ctx: TenantContext,
    ) -> list[AgentSession]:
        """List all active and historical sessions within the caller's tenant/workspace."""
        ...

    async def list_all_sessions_fleet(self) -> list[AgentSession]:
        """System-level method for telemetry scrapers to aggregate fleet status across tenants."""
        ...

    async def add_session_cost(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        cost_usd: float,
    ) -> AgentSession:
        """Atomically increment accumulated_cost_usd on an existing session."""
        ...


@runtime_checkable
class BudgetStore(Protocol):
    """Port for atomic pre-execution budget enforcement (Redis Lua in production)."""

    async def reserve_budget(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        requested_usd: float,
        hard_cap_usd: float,
    ) -> float:
        """Atomically verify and increment session spend; raise BudgetExceededError if over cap."""
        ...

    async def release_budget(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        amount_usd: float,
    ) -> float:
        """Atomically refund or reconcile unused reserved budget."""
        ...

    async def get_spend(self, ctx: TenantContext, session_id: uuid.UUID) -> float:
        """Return current accumulated spend in USD for a session."""
        ...


@runtime_checkable
class AuditStore(Protocol):
    """Port for tamper-evident SHA-256 hash-chained compliance audit logs."""

    async def append_event(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> AuditLogEntry:
        """Append a cryptographically linked entry to the session's audit chain."""
        ...

    async def get_session_audit_log(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[AuditLogEntry]:
        """Return all audit entries for a session in chronological chain order."""
        ...

    async def verify_session_chain(self, ctx: TenantContext, session_id: uuid.UUID) -> bool:
        """Verify the entire SHA-256 hash chain from genesis to tip."""
        ...

    async def verify_session_chain_detailed(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> AuditVerificationResult:
        """Verify chain from genesis to tip, identifying exact block index and violation."""
        ...

    async def query_audit_entries(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID | None = None,
        event_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditLogEntry], int]:
        """Query audit entries across workspace/tenant with optional filters and pagination."""
        ...


@runtime_checkable
class EventSubscription(Protocol):
    """Protocol for an active async event subscription stream with clean closure."""

    def __aiter__(self) -> EventSubscription:
        ...

    async def __anext__(self) -> dict[str, Any]:
        ...

    async def aclose(self) -> None:
        ...


@runtime_checkable
class EventBus(Protocol):
    """Port for distributed C2 wakeup signaling and live WebSocket telemetry fan-out."""

    async def publish(
        self,
        ctx: TenantContext,
        channel: str,
        event: dict[str, Any],
    ) -> None:
        """Publish a tenant-scoped event to all subscribers on channel."""
        ...

    def subscribe(
        self,
        ctx: TenantContext,
        channel: str = "*",
        patterns: Sequence[str] | None = None,
        patterns_set: set[str] | None = None,
    ) -> EventSubscription:
        """Yield live events published to the tenant-scoped channel or matching patterns."""
        ...
