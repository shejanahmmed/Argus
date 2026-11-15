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
        JsonPatchOp(op="add", path="/plan/-", value="step4"),
        JsonPatchOp(op="add", path="/approved_by", value="human_op"),
    )

    patched = apply_json_patch(doc, patch)
    plan_list = list(patched["plan"])
    assert patched["metadata"]["temperature"] == 0.2
    assert plan_list == ["step1", "step2", "step3", "step4"]
    assert patched["approved_by"] == "human_op"

    # Original document is unchanged
    assert doc["metadata"]["temperature"] == 0.7


def test_rfc6902_move_and_copy_operations() -> None:
    doc: dict[str, Any] = {
        "source": {"auth_token": "secret_abc", "env": "prod"},
        "backup": {},
        "numbers": [10, 20, 30],
    }

    patch = (
        # Copy /source/env to /backup/env
        JsonPatchOp(op="copy", path="/backup/env", from_path="/source/env"),
        # Move /numbers/1 (20) to end of numbers
        JsonPatchOp(op="move", path="/numbers/-", from_path="/numbers/1"),
        # Move /source/auth_token to /backup/token
        JsonPatchOp(op="move", path="/backup/token", from_path="/source/auth_token"),
    )

    patched = apply_json_patch(doc, patch)
    assert patched["backup"]["env"] == "prod"
    assert patched["backup"]["token"] == "secret_abc"
    assert "auth_token" not in patched["source"]
    assert patched["numbers"] == [10, 30, 20]


def test_rfc6901_pointer_unescaping() -> None:
    doc: dict[str, Any] = {
        "a/b": "val_slash",
        "m~n": "val_tilde",
        "nested": {"path/with/slashes": 42},
    }

    patch = (
        JsonPatchOp(op="test", path="/a~1b", value="val_slash"),
        JsonPatchOp(op="test", path="/m~0n", value="val_tilde"),
        JsonPatchOp(op="replace", path="/nested/path~1with~1slashes", value=99),
    )
    patched = apply_json_patch(doc, patch)
    assert patched["nested"]["path/with/slashes"] == 99


def test_rfc6902_error_conditions() -> None:
    doc: dict[str, Any] = {"status": "active", "items": ["x", "y"]}

    # 1. Test operation failure
    with pytest.raises(ValueError, match="JSON Patch 'test' failed"):
        apply_json_patch(doc, (JsonPatchOp(op="test", path="/status", value="failed"),))

    # 2. Cannot remove root
    with pytest.raises(ValueError, match="Cannot remove root"):
        apply_json_patch(doc, (JsonPatchOp(op="remove", path="/"),))

    # 3. Circular move into child path
    with pytest.raises(ValueError, match="own child path"):
        apply_json_patch(
            {"parent": {"child": 1}},
            (JsonPatchOp(op="move", path="/parent/child/grandchild", from_path="/parent"),),
        )

    # 4. Out of bounds list index on remove
    with pytest.raises(IndexError, match="out of bounds"):
        apply_json_patch(doc, (JsonPatchOp(op="remove", path="/items/5"),))


@pytest.mark.asyncio
async def test_c2_state_manager_presets_and_timeline() -> None:
    store = InMemoryControlStore()
    manager = C2StateManager(control_store=store)
    ctx = TenantContext(
        tenant_id="tenant_p",
        workspace_id="ws_p",
        actor_id="admin_1",
        role=Role.ADMIN,
    )
    session_id = new_uuid7()

    session = AgentSession(
        session_id=session_id,
        tenant_id="tenant_p",
        workspace_id="ws_p",
        workflow_id="wf_preset",
        agent_name="remediator",
        framework=AgentFramework.LANGGRAPH,
        budget_cap_usd=20.0,
        status=SessionStatus.RUNNING,
    )
    await store.create_session(ctx, session)

    cp0 = CheckpointRecord(
        checkpoint_id=new_uuid7(),
        parent_checkpoint_id=None,
        tenant_id="tenant_p",
        workspace_id="ws_p",
        session_id=session_id,
        node_name="initial_step",
        step_index=0,
        memory_state={"plan": ["drop table customer_data"], "target_env": "production"},
    )
    await store.save_checkpoint(ctx, cp0, expected_parent_id=None)

    # Pause session
    await manager.pause_session(ctx, session_id, reason="Security review")

    # Apply 'force-sandbox-replica' preset
    cp1 = await manager.apply_preset(
        ctx=ctx,
        session_id=session_id,
        preset_id="force-sandbox-replica",
        operator_id="admin_1",
    )
    assert cp1.parent_checkpoint_id == cp0.checkpoint_id
    assert cp1.memory_state["target_env"] == "isolated_sandbox_replica"
    assert cp1.memory_state["read_only"] is True

    # Apply 'safe-fallback-plan' preset
    cp2 = await manager.apply_preset(
        ctx=ctx,
        session_id=session_id,
        preset_id="safe-fallback-plan",
        operator_id="admin_1",
    )
    assert cp2.parent_checkpoint_id == cp1.checkpoint_id
    assert "read-only schema" in cp2.memory_state["plan"][0]

    # Verify list_checkpoints chronological history
    timeline = await manager.list_checkpoints(ctx, session_id)
    assert len(timeline) == 3
    assert [c.step_index for c in timeline] == [0, 1, 2]


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

    # 3. Reject with matching digest succeeds
    cmd_reject = C2OverrideCommand(
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
            request_digest_sha256=digest,
            rejection_reason="Blocked due to suspicious beneficiary",
        ),
        reason="Security block",
    )
    rej_payload, should_exec_rej, msg_rej = engine.process_override(ctx, cmd_reject, pending)
    assert should_exec_rej is False
    assert rej_payload["error"] == "TOOL_EXECUTION_REJECTED_BY_OPERATOR"
    assert rej_payload["tool_call_id"] == "call_1"
    assert "rejected" in msg_rej.lower()

    # 4. Approve decision
    cmd_approve = C2OverrideCommand(
        command_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=new_uuid7(),
        expected_checkpoint_id=new_uuid7(),
        operator_id="operator_1",
        operator_role=Role.OPERATOR,
        action="OVERRIDE_TOOL_CALL",
        tool_override=ToolOverrideSpec(
            decision="approve",
            request_digest_sha256=digest,
        ),
        reason="Verified legitimate transaction",
    )
    app_payload, should_exec_app, _ = engine.process_override(ctx, cmd_approve, pending)
    assert should_exec_app is True
    assert app_payload == pending.tool_args

    # 5. Edit decision containing malicious injection must be blocked
    cmd_edit_malicious = C2OverrideCommand(
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
            modified_args={"amount": 50, "note": "pay; rm -rf /"},
        ),
        reason="Attempted malicious override",
    )
    with pytest.raises(ValueError, match="Security threat detected"):
        engine.process_override(ctx, cmd_edit_malicious, pending)

    # 6. Reject with digest mismatch must fail
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
