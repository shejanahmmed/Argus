"""Distributed C2 Worker Lease, Heartbeat & Dead-Man's Switch Manager.

Tracks active agent worker leases and enforces TTL expiration so orphaned
RUNNING or PAUSED_C2 sessions fail safe to TERMINATED (ABORT_SAFE).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.core.ids import utc_now
from argus.core.schemas import SessionStatus
from argus.core.tenancy import TenantContext
from argus.ports.repositories import AuditStore, ControlStore

HeartbeatDirective = Literal["CONTINUE", "PAUSE_FOR_C2", "TERMINATE"]


class WorkerLease(BaseModel):
    """Represents a time-bounded worker lease for an autonomous agent session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: uuid.UUID
    tenant_id: str
    workspace_id: str
    worker_id: str = Field(min_length=1, max_length=128)
    ttl_seconds: float = Field(default=300.0, gt=0.0)
    renewed_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime


class HeartbeatStatus(BaseModel):
    """Response returned to an agent worker upon heartbeat renewal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: uuid.UUID
    worker_id: str
    session_status: SessionStatus
    directive: HeartbeatDirective
    expires_at: datetime
    latest_checkpoint_id: uuid.UUID | None = None


class C2LeaseManager:
    """Manages distributed worker heartbeats and Dead-Man's Switch lease reaping."""

    def __init__(
        self,
        control_store: ControlStore,
        audit_store: AuditStore,
    ) -> None:
        self._control_store = control_store
        self._audit_store = audit_store
        self._leases: dict[uuid.UUID, WorkerLease] = {}

    async def renew_lease(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID,
        worker_id: str,
        ttl_seconds: float = 300.0,
        now: datetime | None = None,
    ) -> HeartbeatStatus:
        """Renew a session's worker lease and return live C2 control directives."""
        session = await self._control_store.get_session(ctx, session_id)
        current_time = now or utc_now()
        expires_at = current_time + timedelta(seconds=ttl_seconds)

        lease = WorkerLease(
            session_id=session_id,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            worker_id=worker_id,
            ttl_seconds=ttl_seconds,
            renewed_at=current_time,
            expires_at=expires_at,
        )
        self._leases[session_id] = lease

        if session.status == SessionStatus.RUNNING:
            directive: HeartbeatDirective = "CONTINUE"
        elif session.status == SessionStatus.PAUSED_C2:
            directive = "PAUSE_FOR_C2"
        else:
            directive = "TERMINATE"

        return HeartbeatStatus(
            session_id=session_id,
            worker_id=worker_id,
            session_status=session.status,
            directive=directive,
            expires_at=expires_at,
            latest_checkpoint_id=session.latest_checkpoint_id,
        )

    async def reap_expired_leases(
        self,
        ctx: TenantContext,
        *,
        now: datetime | None = None,
    ) -> list[uuid.UUID]:
        """Execute Dead-Man's Switch on expired leases within the caller's tenant/workspace."""
        current_time = now or utc_now()
        reaped: list[uuid.UUID] = []

        for session_id, lease in list(self._leases.items()):
            if lease.tenant_id != ctx.tenant_id or lease.workspace_id != ctx.workspace_id:
                continue
            if current_time < lease.expires_at:
                continue

            session = await self._control_store.get_session(ctx, session_id)
            if session.status in (
                SessionStatus.RUNNING,
                SessionStatus.PAUSED_C2,
                SessionStatus.TRIPPED_LOOP,
                SessionStatus.TRIPPED_BUDGET,
            ):
                await self._control_store.transition_session(
                    ctx=ctx,
                    session_id=session_id,
                    expected_status=session.status,
                    next_status=SessionStatus.TERMINATED,
                )
                await self._audit_store.append_event(
                    ctx=ctx,
                    session_id=session_id,
                    event_type="C2_DEAD_MAN_SWITCH_TERMINATED",
                    payload={
                        "worker_id": lease.worker_id,
                        "previous_status": session.status.value,
                        "expired_at": lease.expires_at.isoformat(),
                        "reaped_at": current_time.isoformat(),
                        "reason": "Worker heartbeat or C2 pause TTL lease expired (ABORT_SAFE).",
                    },
                )
                reaped.append(session_id)

            del self._leases[session_id]

        return reaped

    def clear(self) -> None:
        """Reset tracked leases for test isolation."""
        self._leases.clear()
