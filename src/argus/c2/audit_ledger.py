"""Compliance audit logging helper for recording C2 operator interventions into SHA-256 chain."""

from __future__ import annotations

import uuid
from typing import Any

from argus.core.schemas import AuditLogEntry, C2OverrideCommand
from argus.core.tenancy import TenantContext
from argus.ports.repositories import AuditStore


class C2AuditLedger:
    """Helper recording all C2 interventions into the immutable audit chain."""

    def __init__(self, audit_store: AuditStore) -> None:
        self._store = audit_store

    async def record_intervention(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        command: C2OverrideCommand,
        details: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """Append a C2 operator intervention into the tamper-evident audit store."""
        payload = {
            "command_id": str(command.command_id),
            "action": command.action,
            "operator_id": command.operator_id,
            "operator_role": command.operator_role.value,
            "reason": command.reason,
            "expected_checkpoint_id": str(command.expected_checkpoint_id),
            "details": details or {},
        }
        return await self._store.append_event(
            ctx=ctx,
            session_id=session_id,
            event_type=f"C2_{command.action}",
            payload=payload,
        )
