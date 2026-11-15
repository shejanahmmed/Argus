"""Distributed C2 Worker Lease, Heartbeat & Dead-Man's Switch Manager.

Tracks active agent worker leases and enforces TTL expiration so orphaned
RUNNING or PAUSED_C2 sessions fail safe to TERMINATED (ABORT_SAFE).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.core.errors import EntityNotFoundError
from argus.core.ids import utc_now
from argus.core.schemas import SessionStatus
from argus.core.tenancy import Role, TenantContext
from argus.ports.repositories import AuditStore, ControlStore, EventBus

logger = logging.getLogger("argus.c2.lease_manager")

HeartbeatDirective = Literal["CONTINUE", "PAUSE_FOR_C2", "TERMINATE"]


class WorkerLease(BaseModel):
    """Represents an active time-bounded worker lease for an autonomous agent session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: uuid.UUID
    tenant_id: str
    workspace_id: str
    worker_id: str = Field(min_length=1, max_length=128)
    ttl_seconds: float = Field(default=300.0, gt=0.0)
    renewed_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return True if this lease has exceeded its expiration deadline."""
        current_time = now or utc_now()
        return current_time >= self.expires_at

    def ttl_remaining_seconds(self, now: datetime | None = None) -> float:
        """Return the number of seconds remaining before lease expiration."""
        current_time = now or utc_now()
        return max(0.0, (self.expires_at - current_time).total_seconds())


class HeartbeatStatus(BaseModel):
    """Response returned to an agent worker upon heartbeat renewal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: uuid.UUID
    worker_id: str
    session_status: SessionStatus
    directive: HeartbeatDirective
    expires_at: datetime
    ttl_remaining_seconds: float = 0.0
    server_time: datetime = Field(default_factory=utc_now)
    latest_checkpoint_id: uuid.UUID | None = None
    pending_tool_calls_count: int = 0
    directive_reason: str | None = None


class LeaseSummary(BaseModel):
    """Summary of an active or historical worker lease exposed via management APIs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: uuid.UUID
    tenant_id: str
    workspace_id: str
    worker_id: str
    ttl_seconds: float
    renewed_at: datetime
    expires_at: datetime
    ttl_remaining_seconds: float
    is_expired: bool
    session_status: SessionStatus | None = None


class C2LeaseManager:
    """Manages distributed worker heartbeats and Dead-Man's Switch lease reaping."""

    def __init__(
        self,
        control_store: ControlStore,
        audit_store: AuditStore,
        event_bus: EventBus | None = None,
        min_ttl_seconds: float = 5.0,
        max_ttl_seconds: float = 3600.0,
    ) -> None:
        self._control_store = control_store
        self._audit_store = audit_store
        self._event_bus = event_bus
        self._min_ttl = min_ttl_seconds
        self._max_ttl = max_ttl_seconds
        self._leases: dict[uuid.UUID, WorkerLease] = {}
        self._reaper_task: asyncio.Task[None] | None = None

    async def renew_lease(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID,
        worker_id: str,
        ttl_seconds: float = 300.0,
        pending_tool_calls_count: int = 0,
        now: datetime | None = None,
    ) -> HeartbeatStatus:
        """Renew a session's worker lease and return live C2 control directives."""
        session = await self._control_store.get_session(ctx, session_id)
        current_time = now or utc_now()

        # Enforce bounded TTL policy
        clamped_ttl = max(self._min_ttl, min(ttl_seconds, self._max_ttl))
        expires_at = current_time + timedelta(seconds=clamped_ttl)

        # Derive heartbeat control directive based on session lifecycle state
        directive_reason: str
        if session.status == SessionStatus.RUNNING:
            directive: HeartbeatDirective = "CONTINUE"
            directive_reason = "Session is actively RUNNING."
        elif session.status == SessionStatus.PAUSED_C2:
            directive = "PAUSE_FOR_C2"
            directive_reason = (
                "Session is PAUSED_C2 awaiting operator review or tool override."
            )
        elif session.status in (
            SessionStatus.TRIPPED_LOOP,
            SessionStatus.TRIPPED_BUDGET,
        ):
            directive = "PAUSE_FOR_C2"
            directive_reason = (
                f"Session circuit breaker tripped ({session.status.value})."
            )
        else:
            directive = "TERMINATE"
            directive_reason = (
                f"Session has reached terminal state ({session.status.value})."
            )

        if session.status in (
            SessionStatus.RUNNING,
            SessionStatus.PAUSED_C2,
            SessionStatus.TRIPPED_LOOP,
            SessionStatus.TRIPPED_BUDGET,
        ):
            lease = WorkerLease(
                session_id=session_id,
                tenant_id=ctx.tenant_id,
                workspace_id=ctx.workspace_id,
                worker_id=worker_id,
                ttl_seconds=clamped_ttl,
                renewed_at=current_time,
                expires_at=expires_at,
            )
            self._leases[session_id] = lease
        else:
            # If session is already terminal, clean up any existing lease
            self._leases.pop(session_id, None)

        ttl_remaining = max(0.0, (expires_at - current_time).total_seconds())

        return HeartbeatStatus(
            session_id=session_id,
            worker_id=worker_id,
            session_status=session.status,
            directive=directive,
            expires_at=expires_at,
            ttl_remaining_seconds=ttl_remaining,
            server_time=current_time,
            latest_checkpoint_id=session.latest_checkpoint_id,
            pending_tool_calls_count=pending_tool_calls_count,
            directive_reason=directive_reason,
        )

    async def get_lease(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        now: datetime | None = None,
    ) -> LeaseSummary:
        """Fetch the active worker lease for a session or raise EntityNotFoundError."""
        current_time = now or utc_now()
        lease = self._leases.get(session_id)
        if lease is None:
            raise EntityNotFoundError("WorkerLease", str(session_id))

        if lease.tenant_id != ctx.tenant_id or lease.workspace_id != ctx.workspace_id:
            raise EntityNotFoundError("WorkerLease", str(session_id))

        session = await self._control_store.get_session(ctx, session_id)
        return LeaseSummary(
            session_id=lease.session_id,
            tenant_id=lease.tenant_id,
            workspace_id=lease.workspace_id,
            worker_id=lease.worker_id,
            ttl_seconds=lease.ttl_seconds,
            renewed_at=lease.renewed_at,
            expires_at=lease.expires_at,
            ttl_remaining_seconds=lease.ttl_remaining_seconds(current_time),
            is_expired=lease.is_expired(current_time),
            session_status=session.status,
        )

    async def list_leases(
        self,
        ctx: TenantContext,
        *,
        active_only: bool = True,
        now: datetime | None = None,
    ) -> list[LeaseSummary]:
        """List tracked worker leases within the caller's tenant/workspace."""
        current_time = now or utc_now()
        summaries: list[LeaseSummary] = []

        for session_id, lease in list(self._leases.items()):
            if lease.tenant_id != ctx.tenant_id or lease.workspace_id != ctx.workspace_id:
                continue

            is_expired = lease.is_expired(current_time)
            if active_only and is_expired:
                continue

            try:
                session = await self._control_store.get_session(ctx, session_id)
                session_status = session.status
            except EntityNotFoundError:
                session_status = None

            summaries.append(
                LeaseSummary(
                    session_id=lease.session_id,
                    tenant_id=lease.tenant_id,
                    workspace_id=lease.workspace_id,
                    worker_id=lease.worker_id,
                    ttl_seconds=lease.ttl_seconds,
                    renewed_at=lease.renewed_at,
                    expires_at=lease.expires_at,
                    ttl_remaining_seconds=lease.ttl_remaining_seconds(current_time),
                    is_expired=is_expired,
                    session_status=session_status,
                )
            )

        return summaries

    async def release_lease(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID,
        worker_id: str,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Voluntarily release a worker lease upon graceful agent shutdown."""
        current_time = now or utc_now()
        lease = self._leases.get(session_id)
        if lease is None:
            return False

        if lease.tenant_id != ctx.tenant_id or lease.workspace_id != ctx.workspace_id:
            return False

        del self._leases[session_id]

        await self._audit_store.append_event(
            ctx=ctx,
            session_id=session_id,
            event_type="C2_WORKER_LEASE_RELEASED",
            payload={
                "worker_id": worker_id,
                "reason": reason or "Worker gracefully released lease upon task shutdown.",
                "released_at": current_time.isoformat(),
            },
        )
        return True

    async def reap_expired_leases(
        self,
        ctx: TenantContext,
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> list[uuid.UUID]:
        """Execute Dead-Man's Switch on expired leases within the caller's tenant/workspace."""
        current_time = now or utc_now()
        reaped: list[uuid.UUID] = []

        for session_id, lease in list(self._leases.items()):
            if lease.tenant_id != ctx.tenant_id or lease.workspace_id != ctx.workspace_id:
                continue
            if not lease.is_expired(current_time):
                continue

            if dry_run:
                reaped.append(session_id)
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
                        "reason": (
                            "Worker heartbeat or C2 pause TTL lease expired (ABORT_SAFE)."
                        ),
                    },
                )

                if self._event_bus is not None:
                    await self._event_bus.publish(
                        ctx,
                        channel="c2.dead_man_switch_triggered",
                        event={
                            "session_id": str(session_id),
                            "worker_id": lease.worker_id,
                            "new_status": "TERMINATED",
                            "expired_at": lease.expires_at.isoformat(),
                            "reaped_at": current_time.isoformat(),
                        },
                    )
                    await self._event_bus.publish(
                        ctx,
                        channel="c2.state_changed",
                        event={
                            "session_id": str(session_id),
                            "new_status": "TERMINATED",
                            "reason": "DEAD_MAN_SWITCH_EXPIRED",
                        },
                    )

                reaped.append(session_id)

            del self._leases[session_id]

        return reaped

    async def reap_expired_leases_fleet(
        self,
        *,
        now: datetime | None = None,
    ) -> list[uuid.UUID]:
        """Execute Dead-Man's Switch across all tenants (used by autonomous background task)."""
        current_time = now or utc_now()
        reaped: list[uuid.UUID] = []

        for session_id, lease in list(self._leases.items()):
            if not lease.is_expired(current_time):
                continue

            ctx = TenantContext(
                tenant_id=lease.tenant_id,
                workspace_id=lease.workspace_id,
                actor_id="system_dead_man_reaper",
                role=Role.ADMIN,
            )

            try:
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
                            "reason": (
                                "Autonomous background Dead-Man's switch reaper sweep (ABORT_SAFE)."
                            ),
                        },
                    )

                    if self._event_bus is not None:
                        await self._event_bus.publish(
                            ctx,
                            channel="c2.dead_man_switch_triggered",
                            event={
                                "session_id": str(session_id),
                                "worker_id": lease.worker_id,
                                "new_status": "TERMINATED",
                                "expired_at": lease.expires_at.isoformat(),
                                "reaped_at": current_time.isoformat(),
                            },
                        )
                        await self._event_bus.publish(
                            ctx,
                            channel="c2.state_changed",
                            event={
                                "session_id": str(session_id),
                                "new_status": "TERMINATED",
                                "reason": "DEAD_MAN_SWITCH_EXPIRED",
                            },
                        )

                    reaped.append(session_id)
            except Exception as e:
                logger.warning(
                    "Error executing Dead-Man reap for session %s: %s",
                    session_id,
                    e,
                )
            finally:
                self._leases.pop(session_id, None)

        return reaped

    async def start_reaper_loop(self, interval_seconds: float = 30.0) -> None:
        """Run continuous background sweeps to reap expired worker leases."""
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                await self.reap_expired_leases_fleet()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error during background Dead-Man lease reaper sweep: %s", e)

    def start_background_reaper(self, interval_seconds: float = 30.0) -> None:
        """Start the background reaper task if not already running."""
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(
                self.start_reaper_loop(interval_seconds)
            )

    def stop_background_reaper(self) -> None:
        """Stop the background reaper task."""
        if self._reaper_task is not None and not self._reaper_task.done():
            self._reaper_task.cancel()
            self._reaper_task = None

    def clear(self) -> None:
        """Reset tracked leases for test isolation."""
        self.stop_background_reaper()
        self._leases.clear()
