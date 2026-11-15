"""Deterministic async in-memory adapters implementing Argus hexagonal ports for testing."""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from typing import Any

from argus.core.errors import (
    BudgetExceededError,
    CheckpointConflictError,
    EntityNotFoundError,
    InvalidStateTransitionError,
)
from argus.core.ids import new_uuid7
from argus.core.schemas import (
    GENESIS_AUDIT_HASH,
    AgentSession,
    ArgusSpan,
    AuditLogEntry,
    AuditVerificationResult,
    CheckpointRecord,
    SessionStatus,
)
from argus.core.tenancy import TenantContext


class InMemoryTraceStore:
    """Thread/coroutine-safe in-memory implementation of the TraceStore port."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._spans: list[ArgusSpan] = []

    async def append_spans(self, ctx: TenantContext, spans: Sequence[ArgusSpan]) -> int:
        for span in spans:
            ctx.assert_same_tenant(span.tenant_id, span.workspace_id)
        async with self._lock:
            self._spans.extend(spans)
        return len(spans)

    async def get_trace_subtree(
        self,
        ctx: TenantContext,
        root_dotted_order: str,
    ) -> list[ArgusSpan]:
        prefix_dot = f"{root_dotted_order}."
        async with self._lock:
            matched = [
                s
                for s in self._spans
                if s.tenant_id == ctx.tenant_id
                and s.workspace_id == ctx.workspace_id
                and (s.dotted_order == root_dotted_order or s.dotted_order.startswith(prefix_dot))
            ]
        return sorted(matched, key=lambda s: s.dotted_order)

    async def get_session_spans(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[ArgusSpan]:
        async with self._lock:
            matched = [
                s
                for s in self._spans
                if s.tenant_id == ctx.tenant_id
                and s.workspace_id == ctx.workspace_id
                and s.session_id == session_id
            ]
        return sorted(matched, key=lambda s: s.dotted_order)


class InMemoryControlStore:
    """Coroutine-safe in-memory implementation of the ControlStore port."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[uuid.UUID, AgentSession] = {}
        self._checkpoints: dict[uuid.UUID, list[CheckpointRecord]] = defaultdict(list)

    async def create_session(self, ctx: TenantContext, session: AgentSession) -> AgentSession:
        ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
        async with self._lock:
            self._sessions[session.session_id] = session
        return session

    async def get_session(self, ctx: TenantContext, session_id: uuid.UUID) -> AgentSession:
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise EntityNotFoundError("AgentSession", str(session_id))
        ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
        return session

    async def transition_session(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        expected_status: SessionStatus,
        next_status: SessionStatus,
    ) -> AgentSession:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
            if session.status != expected_status:
                raise InvalidStateTransitionError(session.status.value, next_status.value)
            updated = session.transition_to(next_status)
            self._sessions[session_id] = updated
            return updated

    async def save_checkpoint(
        self,
        ctx: TenantContext,
        checkpoint: CheckpointRecord,
        expected_parent_id: uuid.UUID | None,
    ) -> CheckpointRecord:
        ctx.assert_same_tenant(checkpoint.tenant_id, checkpoint.workspace_id)
        async with self._lock:
            session = self._sessions.get(checkpoint.session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(checkpoint.session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)

            history = self._checkpoints[checkpoint.session_id]
            current_latest_id = history[-1].checkpoint_id if history else None

            if current_latest_id != expected_parent_id:
                raise CheckpointConflictError(
                    expected_id=str(expected_parent_id),
                    actual_id=str(current_latest_id) if current_latest_id else None,
                )

            history.append(checkpoint)
            self._sessions[checkpoint.session_id] = session.model_copy(
                update={"latest_checkpoint_id": checkpoint.checkpoint_id}
            )
            return checkpoint

    async def get_latest_checkpoint(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> CheckpointRecord | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
            history = self._checkpoints.get(session_id, [])
            return history[-1] if history else None

    async def list_checkpoints(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[CheckpointRecord]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
            return list(self._checkpoints.get(session_id, []))

    async def list_sessions(
        self,
        ctx: TenantContext,
    ) -> list[AgentSession]:
        async with self._lock:
            return [
                session
                for session in self._sessions.values()
                if session.tenant_id == ctx.tenant_id and session.workspace_id == ctx.workspace_id
            ]

    async def list_all_sessions_fleet(self) -> list[AgentSession]:
        async with self._lock:
            return list(self._sessions.values())

    async def add_session_cost(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        cost_usd: float,
    ) -> AgentSession:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
            new_cost = round(session.accumulated_cost_usd + max(0.0, cost_usd), 8)
            updated = session.model_copy(update={"accumulated_cost_usd": new_cost})
            self._sessions[session_id] = updated
            return updated


class InMemoryBudgetStore:
    """Atomic coroutine-safe in-memory implementation of the BudgetStore port."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._spend: dict[tuple[str, str, uuid.UUID], float] = defaultdict(float)

    async def reserve_budget(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        requested_usd: float,
        hard_cap_usd: float,
    ) -> float:
        if requested_usd < 0.0:
            raise ValueError("requested_usd cannot be negative.")
        if hard_cap_usd <= 0.0:
            raise ValueError("hard_cap_usd must be positive.")

        key = (ctx.tenant_id, ctx.workspace_id, session_id)
        async with self._lock:
            current = self._spend[key]
            projected = round(current + requested_usd, 8)
            if projected > hard_cap_usd:
                raise BudgetExceededError(
                    session_id=str(session_id),
                    accumulated_usd=current,
                    requested_usd=requested_usd,
                    hard_cap_usd=hard_cap_usd,
                )
            self._spend[key] = projected
            return projected

    async def release_budget(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        amount_usd: float,
    ) -> float:
        if amount_usd < 0.0:
            raise ValueError("amount_usd cannot be negative.")
        key = (ctx.tenant_id, ctx.workspace_id, session_id)
        async with self._lock:
            current = self._spend[key]
            updated = max(0.0, round(current - amount_usd, 8))
            self._spend[key] = updated
            return updated

    async def get_spend(self, ctx: TenantContext, session_id: uuid.UUID) -> float:
        key = (ctx.tenant_id, ctx.workspace_id, session_id)
        async with self._lock:
            return self._spend[key]


class InMemoryAuditStore:
    """Tamper-evident SHA-256 hash-chained in-memory AuditStore."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._chains: dict[tuple[str, str, uuid.UUID], list[AuditLogEntry]] = defaultdict(list)

    async def append_event(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> AuditLogEntry:
        key = (ctx.tenant_id, ctx.workspace_id, session_id)
        async with self._lock:
            chain = self._chains[key]
            prev_hash = chain[-1].entry_hash if chain else GENESIS_AUDIT_HASH
            entry = AuditLogEntry.create_linked(
                audit_id=new_uuid7(),
                tenant_id=ctx.tenant_id,
                workspace_id=ctx.workspace_id,
                session_id=session_id,
                actor_id=ctx.actor_id,
                actor_role=ctx.role,
                event_type=event_type,
                payload=payload,
                prev_entry_hash=prev_hash,
            )
            chain.append(entry)
            return entry

    async def get_session_audit_log(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[AuditLogEntry]:
        key = (ctx.tenant_id, ctx.workspace_id, session_id)
        async with self._lock:
            return list(self._chains.get(key, []))

    async def verify_session_chain(self, ctx: TenantContext, session_id: uuid.UUID) -> bool:
        report = await self.verify_session_chain_detailed(ctx, session_id)
        return report.is_valid

    async def verify_session_chain_detailed(
        self, ctx: TenantContext, session_id: uuid.UUID
    ) -> AuditVerificationResult:
        """Verify chain from genesis to tip, identifying exact block index and violation."""
        entries = await self.get_session_audit_log(ctx, session_id)
        expected_prev = GENESIS_AUDIT_HASH
        tip_hash = entries[-1].entry_hash if entries else None

        for idx, entry in enumerate(entries):
            valid, violation_type, violation_details = entry.check_integrity_detailed(
                expected_prev
            )
            if not valid:
                return AuditVerificationResult(
                    session_id=session_id,
                    is_valid=False,
                    total_entries=len(entries),
                    genesis_hash=GENESIS_AUDIT_HASH,
                    tip_hash=tip_hash,
                    tampered_entry_index=idx,
                    tampered_audit_id=entry.audit_id,
                    violation_type=violation_type,
                    violation_details=violation_details,
                )
            expected_prev = entry.entry_hash

        return AuditVerificationResult(
            session_id=session_id,
            is_valid=True,
            total_entries=len(entries),
            genesis_hash=GENESIS_AUDIT_HASH,
            tip_hash=tip_hash,
        )

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
        async with self._lock:
            all_matched: list[AuditLogEntry] = []
            for (tid, wid, sid), chain in self._chains.items():
                if tid != ctx.tenant_id or wid != ctx.workspace_id:
                    continue
                if session_id is not None and sid != session_id:
                    continue
                for entry in chain:
                    if event_type is not None and entry.event_type != event_type:
                        continue
                    if actor_id is not None and entry.actor_id != actor_id:
                        continue
                    all_matched.append(entry)

            all_matched.sort(key=lambda e: e.created_at)
            total = len(all_matched)
            paged = all_matched[offset : offset + limit]
            return paged, total


class InMemoryEventBus:
    """Tenant-isolated async pub/sub event bus for C2 wakeups and live telemetry."""

    def __init__(self) -> None:
        self._subscribers: dict[tuple[str, str, str], set[asyncio.Queue[dict[str, Any]]]] = (
            defaultdict(set)
        )

    async def publish(
        self,
        ctx: TenantContext,
        channel: str,
        event: dict[str, Any],
    ) -> None:
        key = (ctx.tenant_id, ctx.workspace_id, channel)
        for queue in list(self._subscribers.get(key, set())):
            await queue.put(event)

        if channel != "*":
            wildcard_key = (ctx.tenant_id, ctx.workspace_id, "*")
            wildcard_envelope = {"channel": channel, "event": event, **event}
            for queue in list(self._subscribers.get(wildcard_key, set())):
                await queue.put(wildcard_envelope)

    def subscribe(
        self,
        ctx: TenantContext,
        channel: str,
    ) -> AsyncIterator[dict[str, Any]]:
        # Register the subscriber queue eagerly upon calling subscribe() rather than inside
        # the async generator body so events published before the first anext() are not lost.
        key = (ctx.tenant_id, ctx.workspace_id, channel)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[key].add(queue)

        async def _stream() -> AsyncIterator[dict[str, Any]]:
            try:
                while True:
                    item = await queue.get()
                    yield item
            finally:
                self._subscribers[key].discard(queue)

        return _stream()
