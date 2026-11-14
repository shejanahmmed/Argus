"""RFC 6902 JSON Patch application engine and distributed C2 State Manager.

Enforces optimistic concurrency control (expected_checkpoint_id) so operators can
safely inspect and mutate agent memory mid-execution without causing split-brain states.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from argus.core.errors import CheckpointConflictError, EntityNotFoundError
from argus.core.ids import new_uuid7, utc_now
from argus.core.schemas import (
    AgentSession,
    C2OverrideCommand,
    CheckpointRecord,
    JsonPatchOp,
    SessionStatus,
)
from argus.core.tenancy import TenantContext
from argus.ports.repositories import ControlStore


def apply_json_patch(
    document: dict[str, Any],
    patch_ops: tuple[JsonPatchOp, ...],
) -> dict[str, Any]:
    """Apply RFC 6902 patch operations to a document without mutating the original."""
    target = copy.deepcopy(document)

    for op in patch_ops:
        path_parts = [p for p in op.path.strip("/").split("/") if p]
        if not path_parts:
            if op.op == "replace":
                if isinstance(op.value, dict):
                    target = copy.deepcopy(op.value)
                continue
            raise ValueError(f"Root path '/' unsupported for operation '{op.op}'.")

        curr: Any = target
        for part in path_parts[:-1]:
            if isinstance(curr, dict):
                if part not in curr:
                    curr[part] = {}
                curr = curr[part]
            elif isinstance(curr, list):
                idx = int(part)
                curr = curr[idx]

        last_key: Any = path_parts[-1]

        if op.op == "add" or op.op == "replace":
            if isinstance(curr, dict):
                curr[str(last_key)] = copy.deepcopy(op.value)
            elif isinstance(curr, list):
                idx = int(last_key)
                if op.op == "add":
                    curr.insert(idx, copy.deepcopy(op.value))
                else:
                    curr[idx] = copy.deepcopy(op.value)

        elif op.op == "remove":
            if isinstance(curr, dict):
                curr.pop(str(last_key), None)
            elif isinstance(curr, list):
                idx = int(last_key)
                if 0 <= idx < len(curr):
                    curr.pop(idx)

        elif op.op == "test":
            actual_val = curr.get(str(last_key)) if isinstance(curr, dict) else curr[int(last_key)]
            if actual_val != op.value:
                raise ValueError(
                    f"JSON Patch 'test' failed at path '{op.path}': "
                    f"expected {op.value}, found {actual_val}"
                )

    return target


class C2StateManager:
    """Manages distributed Command & Control agent pause, memory patch, and resume lifecycles."""

    def __init__(self, control_store: ControlStore) -> None:
        self._store = control_store

    async def pause_session(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        reason: str,
    ) -> AgentSession:
        """Pause a running agent session for human C2 inspection."""
        ctx.assert_can_mutate_c2()
        return await self._store.transition_session(
            ctx=ctx,
            session_id=session_id,
            expected_status=SessionStatus.RUNNING,
            next_status=SessionStatus.PAUSED_C2,
        )

    async def apply_memory_patch(
        self,
        ctx: TenantContext,
        command: C2OverrideCommand,
    ) -> CheckpointRecord:
        """Atomically mutate paused agent memory state via RFC 6902 JSON Patch."""
        ctx.assert_can_mutate_c2()
        ctx.assert_same_tenant(command.tenant_id, command.workspace_id)

        session = await self._store.get_session(ctx, command.session_id)
        if session.status != SessionStatus.PAUSED_C2:
            raise ValueError(
                f"Cannot patch memory for session in status '{session.status}'. "
                "Session must be PAUSED_C2."
            )

        latest_cp = await self._store.get_latest_checkpoint(ctx, command.session_id)
        if latest_cp is None:
            raise EntityNotFoundError("CheckpointRecord", str(command.session_id))

        if latest_cp.checkpoint_id != command.expected_checkpoint_id:
            raise CheckpointConflictError(
                expected_id=str(command.expected_checkpoint_id),
                actual_id=str(latest_cp.checkpoint_id),
            )

        # Apply memory mutations deterministically
        updated_memory = apply_json_patch(latest_cp.memory_state, command.memory_patch)

        new_checkpoint = CheckpointRecord(
            checkpoint_id=new_uuid7(),
            parent_checkpoint_id=latest_cp.checkpoint_id,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=command.session_id,
            node_name=f"{latest_cp.node_name}:c2_edit",
            step_index=latest_cp.step_index + 1,
            memory_state=updated_memory,
            pending_tool_call=latest_cp.pending_tool_call,
            created_at=utc_now(),
        )

        return await self._store.save_checkpoint(
            ctx=ctx,
            checkpoint=new_checkpoint,
            expected_parent_id=latest_cp.checkpoint_id,
        )

    async def resume_session(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> AgentSession:
        """Resume a paused agent session after operator review or mutation."""
        ctx.assert_can_mutate_c2()
        return await self._store.transition_session(
            ctx=ctx,
            session_id=session_id,
            expected_status=SessionStatus.PAUSED_C2,
            next_status=SessionStatus.RUNNING,
        )

    async def terminate_session(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        reason: str,
    ) -> AgentSession:
        """Force terminate an agent session (kill-switch)."""
        ctx.assert_can_mutate_c2()
        session = await self._store.get_session(ctx, session_id)
        return await self._store.transition_session(
            ctx=ctx,
            session_id=session_id,
            expected_status=session.status,
            next_status=SessionStatus.TERMINATED,
        )
