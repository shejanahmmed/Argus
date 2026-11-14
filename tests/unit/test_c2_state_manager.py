"""Unit tests for C2 State Manager, optimistic locking, and tool override engine."""

from __future__ import annotations

from typing import Any

import pytest

from argus.adapters_infra.in_memory import InMemoryControlStore
from argus.c2.state_manager import C2StateManager, apply_json_patch
from argus.c2.tool_override import ToolOverrideEngine
from argus.core.errors import CheckpointConflictError
from argus.core.ids import new_uuid7
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    C2OverrideCommand,
    CheckpointRecord,
    JsonPatchOp,
    PendingToolCall,
    SessionStatus,
    ToolOverrideSpec,
)
from argus.core.tenancy import Role, TenantContext


def test_apply_json_patch_operations() -> None:
    doc: dict[str, Any] = {"plan": ["step1", "step2"], "metadata": {"temperature": 0.7}}

    patch = (
        JsonPatchOp(op="replace", path="/metadata/temperature", value=0.2),
        JsonPatchOp(op="add", path="/plan/2", value="step3"),
        JsonPatchOp(op="add", path="/approved_by", value="human_op"),
    )

    patched = apply_json_patch(doc, patch)
    plan_list = list(patched["plan"])
    assert patched["metadata"]["temperature"] == 0.2
    assert plan_list == ["step1", "step2", "step3"]
    assert patched["approved_by"] == "human_op"

    # Original document is unchanged
    assert doc["metadata"]["temperature"] == 0.7


@pytest.mark.asyncio
async def test_c2_state_manager_pause_and_optimistic_patch() -> None:
    store = InMemoryControlStore()
    manager = C2StateManager(control_store=store)
    ctx = TenantContext(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        actor_id="operator_1",
        role=Role.OPERATOR,
    )
    session_id = new_uuid7()

    session = AgentSession(
        session_id=session_id,
        tenant_id="tenant_a",
        workspace_id="ws_1",
        workflow_id="wf_sec",
        agent_name="db_agent",
        framework=AgentFramework.LANGGRAPH,
        budget_cap_usd=10.0,
    )
    await store.create_session(ctx, session)

    cp1 = CheckpointRecord(
        checkpoint_id=new_uuid7(),
        parent_checkpoint_id=None,
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        node_name="sql_node",
        step_index=0,
        memory_state={"query": "DROP TABLE users"},
    )
    await store.save_checkpoint(ctx, cp1, expected_parent_id=None)

    # Pause session
    paused = await manager.pause_session(ctx, session_id, reason="destructive query detected")
    assert paused.status == SessionStatus.PAUSED_C2

    # Operator issues memory patch with matching expected_checkpoint_id
    cmd = C2OverrideCommand(
        command_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        expected_checkpoint_id=cp1.checkpoint_id,
        operator_id="operator_1",
        operator_role=Role.OPERATOR,
        action="EDIT_MEMORY",
        memory_patch=(
            JsonPatchOp(op="replace", path="/query", value="SELECT * FROM users LIMIT 10"),
        ),
        reason="Safe query substitution",
    )
    new_cp = await manager.apply_memory_patch(ctx, cmd)
    assert new_cp.memory_state["query"] == "SELECT * FROM users LIMIT 10"
    assert new_cp.parent_checkpoint_id == cp1.checkpoint_id

    # Stale patch with old checkpoint ID must be rejected
    stale_cmd = C2OverrideCommand(
        command_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        expected_checkpoint_id=cp1.checkpoint_id,
        operator_id="operator_1",
        operator_role=Role.OPERATOR,
        action="EDIT_MEMORY",
        memory_patch=(JsonPatchOp(op="replace", path="/query", value="SELECT 1"),),
        reason="Stale edit",
    )
    with pytest.raises(CheckpointConflictError):
        await manager.apply_memory_patch(ctx, stale_cmd)


def test_tool_override_engine_decisions() -> None:
    engine = ToolOverrideEngine()
    ctx = TenantContext(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        actor_id="operator_1",
        role=Role.OPERATOR,
    )
    pending = PendingToolCall(
        tool_call_id="call_1",
        tool_name="transfer_funds",
        tool_args={"amount": 1000, "to": "acc_9"},
        is_destructive=True,
    )
    digest = pending.request_digest_sha256

    # 1. Edit decision
    cmd_edit = C2OverrideCommand(
        command_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=new_uuid7(),
        expected_checkpoint_id=new_uuid7(),
        operator_id="operator_1",
        operator_role=Role.OPERATOR,
        action="OVERRIDE_TOOL_CALL",
        tool_override=ToolOverrideSpec(
            decision="edit",
            request_digest_sha256=digest,
            modified_args={"amount": 50, "to": "acc_9"},
        ),
        reason="Exceeded approval limit",
    )
    args, should_exec, _msg = engine.process_override(ctx, cmd_edit, pending)
    assert should_exec is True
    assert args == {"amount": 50, "to": "acc_9"}

    # 2. Mock decision
    cmd_mock = C2OverrideCommand(
        command_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=new_uuid7(),
        expected_checkpoint_id=new_uuid7(),
        operator_id="operator_1",
        operator_role=Role.OPERATOR,
        action="OVERRIDE_TOOL_CALL",
        tool_override=ToolOverrideSpec(
            decision="mock",
            request_digest_sha256=digest,
            mock_output={"transaction_id": "tx_mock_1", "status": "approved"},
        ),
        reason="Mock test",
    )
    mock_payload, should_exec_mock, _ = engine.process_override(ctx, cmd_mock, pending)
    assert should_exec_mock is False
    assert mock_payload["status"] == "approved"

    # 3. Reject with digest mismatch must fail
    cmd_mismatch = C2OverrideCommand(
        command_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=new_uuid7(),
        expected_checkpoint_id=new_uuid7(),
        operator_id="operator_1",
        operator_role=Role.OPERATOR,
        action="OVERRIDE_TOOL_CALL",
        tool_override=ToolOverrideSpec(
            decision="reject",
            request_digest_sha256="0" * 64,
            rejection_reason="Blocked",
        ),
        reason="Digest mismatch test",
    )
    with pytest.raises(ValueError, match="Digest mismatch"):
        engine.process_override(ctx, cmd_mismatch, pending)
