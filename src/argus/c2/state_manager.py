"""RFC 6902 JSON Patch application engine and distributed C2 State Manager.

Enforces optimistic concurrency control (expected_checkpoint_id) so operators can
safely inspect and mutate agent memory mid-execution without causing split-brain states.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Literal

from argus.c2.presets import get_preset
from argus.core.errors import CheckpointConflictError, EntityNotFoundError
from argus.core.ids import new_uuid7, utc_now
from argus.core.schemas import (
    AgentSession,
    C2OverrideCommand,
    CheckpointRecord,
    JsonPatchOp,
    SessionStatus,
)
from argus.core.tenancy import Role, TenantContext
from argus.ports.repositories import ControlStore


def unescape_pointer_token(token: str) -> str:
    """Unescape an RFC 6901 reference token (~1 -> /, ~0 -> ~)."""
    return token.replace("~1", "/").replace("~0", "~")


def parse_json_pointer(pointer: str) -> list[str]:
    """Parse an RFC 6901 JSON Pointer into unescaped path tokens."""
    if not pointer or pointer == "/":
        return []
    if not pointer.startswith("/"):
        raise ValueError(
            f"Invalid JSON Pointer '{pointer}': must begin with '/' or be empty."
        )
    return [unescape_pointer_token(part) for part in pointer[1:].split("/")]


def _resolve_parent_container(
    doc: Any, tokens: list[str], *, create_missing: bool = False
) -> tuple[Any, str]:
    """Resolve the parent container and final token for an RFC 6901 path."""
    if not tokens:
        raise ValueError("Cannot resolve parent of root document.")

    curr = doc
    for i, token in enumerate(tokens[:-1]):
        if isinstance(curr, dict):
            if token not in curr:
                if create_missing:
                    curr[token] = {}
                else:
                    raise KeyError(f"Key '{token}' not found at path segment {i}")
            curr = curr[token]
        elif isinstance(curr, list):
            try:
                idx = int(token)
            except ValueError as err:
                raise IndexError(f"List index '{token}' is not an integer") from err
            if idx < 0 or idx >= len(curr):
                raise IndexError(
                    f"List index {idx} out of bounds [0, {len(curr)}) at segment {i}"
                )
            curr = curr[idx]
        else:
            raise KeyError(
                f"Cannot traverse non-container '{type(curr).__name__}' at segment '{token}'"
            )

    return curr, tokens[-1]


def _resolve_target_value(doc: Any, tokens: list[str]) -> Any:
    """Retrieve the value at an RFC 6901 path or raise KeyError/IndexError."""
    if not tokens:
        return doc
    parent, last_token = _resolve_parent_container(doc, tokens, create_missing=False)
    if isinstance(parent, dict):
        if last_token not in parent:
            raise KeyError(f"Key '{last_token}' not found")
        return parent[last_token]
    if isinstance(parent, list):
        try:
            idx = int(last_token)
        except ValueError as err:
            raise IndexError(f"List index '{last_token}' is not an integer") from err
        if idx < 0 or idx >= len(parent):
            raise IndexError(f"List index {idx} out of bounds [0, {len(parent)})")
        return parent[idx]
    raise KeyError(f"Cannot resolve value in non-container '{type(parent).__name__}'")


def _insert_value(parent: Any, token: str, value: Any) -> None:
    """Helper to insert/append a value into a dict or list according to RFC 6902."""
    if isinstance(parent, dict):
        parent[token] = copy.deepcopy(value)
    elif isinstance(parent, list):
        if token == "-":
            parent.append(copy.deepcopy(value))
        else:
            try:
                idx = int(token)
            except ValueError as err:
                raise IndexError(f"List index '{token}' is not an integer") from err
            if idx < 0 or idx > len(parent):
                raise IndexError(
                    f"List index {idx} out of bounds for insertion [0, {len(parent)}]"
                )
            parent.insert(idx, copy.deepcopy(value))
    else:
        raise ValueError(
            f"Parent container must be dict or list, got '{type(parent).__name__}'."
        )


def _extract_and_remove(parent: Any, token: str) -> Any:
    """Helper to pop a value from a dict or list according to RFC 6902."""
    if isinstance(parent, dict):
        if token not in parent:
            raise KeyError(f"Property '{token}' does not exist for removal.")
        return parent.pop(token)
    if isinstance(parent, list):
        try:
            idx = int(token)
        except ValueError as err:
            raise IndexError(f"List index '{token}' is not an integer") from err
        if idx < 0 or idx >= len(parent):
            raise IndexError(
                f"List index {idx} out of bounds for removal [0, {len(parent)})"
            )
        return parent.pop(idx)
    raise ValueError(
        f"Parent container must be dict or list, got '{type(parent).__name__}'."
    )


def apply_json_patch(
    document: dict[str, Any],
    patch_ops: tuple[JsonPatchOp, ...],
) -> dict[str, Any]:
    """Apply RFC 6902 patch operations to a document without mutating the original.

    Supports operations: add, remove, replace, move, copy, and test with RFC 6901
    unescaping and transactional atomicity.
    """
    target = copy.deepcopy(document)

    for op in patch_ops:
        tokens = parse_json_pointer(op.path)

        # 1. Operation: ADD
        if op.op == "add":
            if not tokens:
                if isinstance(op.value, dict):
                    target = copy.deepcopy(op.value)
                else:
                    raise ValueError("Root document replacement must be a dictionary.")
            else:
                parent, last_token = _resolve_parent_container(
                    target, tokens, create_missing=False
                )
                _insert_value(parent, last_token, op.value)

        # 2. Operation: REMOVE
        elif op.op == "remove":
            if not tokens:
                raise ValueError("Cannot remove root document.")
            parent, last_token = _resolve_parent_container(
                target, tokens, create_missing=False
            )
            _extract_and_remove(parent, last_token)

        # 3. Operation: REPLACE
        elif op.op == "replace":
            if not tokens:
                if isinstance(op.value, dict):
                    target = copy.deepcopy(op.value)
                else:
                    raise ValueError("Root document replacement must be a dictionary.")
            else:
                parent, last_token = _resolve_parent_container(
                    target, tokens, create_missing=False
                )
                if isinstance(parent, dict):
                    if last_token not in parent:
                        raise KeyError(
                            f"Property '{last_token}' does not exist for replace operation."
                        )
                    parent[last_token] = copy.deepcopy(op.value)
                elif isinstance(parent, list):
                    try:
                        idx = int(last_token)
                    except ValueError as err:
                        raise IndexError(
                            f"List index '{last_token}' is not an integer"
                        ) from err
                    if idx < 0 or idx >= len(parent):
                        raise IndexError(
                            f"List index {idx} out of bounds for replace [0, {len(parent)})"
                        )
                    parent[idx] = copy.deepcopy(op.value)
                else:
                    raise ValueError(
                        f"Cannot replace inside non-container '{type(parent).__name__}'."
                    )

        # 4. Operation: MOVE
        elif op.op == "move":
            from_path = op.from_path
            if not from_path:
                raise ValueError("Operation 'move' requires a valid 'from' path.")
            if from_path == op.path:
                continue
            if op.path.startswith(from_path.rstrip("/") + "/"):
                raise ValueError(
                    f"Cannot move '{from_path}' into its own child path '{op.path}'."
                )

            from_tokens = parse_json_pointer(from_path)
            if not from_tokens:
                raise ValueError("Cannot move root document.")

            from_parent, from_token = _resolve_parent_container(
                target, from_tokens, create_missing=False
            )
            extracted = _extract_and_remove(from_parent, from_token)

            if not tokens:
                if isinstance(extracted, dict):
                    target = extracted
                else:
                    raise ValueError("Root document replacement must be a dictionary.")
            else:
                dest_parent, dest_token = _resolve_parent_container(
                    target, tokens, create_missing=False
                )
                _insert_value(dest_parent, dest_token, extracted)

        # 5. Operation: COPY
        elif op.op == "copy":
            from_path = op.from_path
            if not from_path:
                raise ValueError("Operation 'copy' requires a valid 'from' path.")
            from_tokens = parse_json_pointer(from_path)
            copied_val = _resolve_target_value(target, from_tokens)

            if not tokens:
                if isinstance(copied_val, dict):
                    target = copy.deepcopy(copied_val)
                else:
                    raise ValueError("Root document replacement must be a dictionary.")
            else:
                dest_parent, dest_token = _resolve_parent_container(
                    target, tokens, create_missing=False
                )
                _insert_value(dest_parent, dest_token, copied_val)

        # 6. Operation: TEST
        elif op.op == "test":
            actual_val = _resolve_target_value(target, tokens)
            if actual_val != op.value:
                raise ValueError(
                    f"JSON Patch 'test' failed at path '{op.path}': "
                    f"expected {op.value!r}, found {actual_val!r}"
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
        """Pause a running or tripped agent session for human C2 inspection."""
        ctx.assert_can_mutate_c2()
        session = await self._store.get_session(ctx, session_id)
        return await self._store.transition_session(
            ctx=ctx,
            session_id=session_id,
            expected_status=session.status,
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

    async def apply_preset(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        preset_id: str,
        operator_id: str,
        expected_checkpoint_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> CheckpointRecord:
        """Apply a pre-built state preset to a paused session's latest checkpoint."""
        ctx.assert_can_mutate_c2()
        preset = get_preset(preset_id)
        if preset is None:
            raise EntityNotFoundError("StatePreset", preset_id)

        latest_cp = await self._store.get_latest_checkpoint(ctx, session_id)
        if latest_cp is None:
            raise EntityNotFoundError("CheckpointRecord", str(session_id))

        target_parent_id = expected_checkpoint_id or latest_cp.checkpoint_id
        op_role: Literal[Role.OPERATOR, Role.ADMIN] = (
            Role.ADMIN if ctx.role == Role.ADMIN else Role.OPERATOR
        )

        command = C2OverrideCommand(
            command_id=new_uuid7(),
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=session_id,
            expected_checkpoint_id=target_parent_id,
            operator_id=operator_id,
            operator_role=op_role,
            action="EDIT_MEMORY",
            memory_patch=preset.patches,
            reason=reason or f"Applied state preset: {preset.name}",
        )
        return await self.apply_memory_patch(ctx, command)

    async def list_checkpoints(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[CheckpointRecord]:
        """Retrieve full chronological checkpoint history for a session."""
        ctx.assert_same_tenant(ctx.tenant_id, ctx.workspace_id)
        return await self._store.list_checkpoints(ctx, session_id)

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


__all__ = [
    "C2StateManager",
    "apply_json_patch",
    "parse_json_pointer",
    "unescape_pointer_token",
]
