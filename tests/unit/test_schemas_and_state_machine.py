"""Unit tests for strict Pydantic v2 schemas, state transitions, ROI, and audit hashing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from argus.core.errors import (
    AuthorizationError,
    InvalidStateTransitionError,
    TenantIsolationError,
)
from argus.core.ids import build_dotted_order, new_uuid7
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    ArgusSpan,
    AuditLogEntry,
    AuditViolationType,
    C2OverrideCommand,
    JsonPatchOp,
    OperationName,
    PendingToolCall,
    SessionStatus,
    SpanKind,
    ToolOverrideSpec,
    WorkflowROIAttribution,
)
from argus.core.tenancy import Role, TenantContext


def test_tenant_context_isolation_and_rbac() -> None:
    viewer_ctx = TenantContext(
        tenant_id="acme_corp",
        workspace_id="prod_us",
        actor_id="user_1",
        role=Role.VIEWER,
    )
    viewer_ctx.assert_same_tenant("acme_corp", "prod_us")

    with pytest.raises(TenantIsolationError):
        viewer_ctx.assert_same_tenant("other_tenant", "prod_us")

    with pytest.raises(AuthorizationError):
        viewer_ctx.assert_can_mutate_c2()

    op_ctx = TenantContext(
        tenant_id="acme_corp",
        workspace_id="prod_us",
        actor_id="op_1",
        role=Role.OPERATOR,
    )
    op_ctx.assert_can_mutate_c2()


def test_session_state_machine_transitions() -> None:
    session = AgentSession(
        session_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        workflow_id="wf_billing",
        agent_name="billing_agent",
        framework=AgentFramework.LANGGRAPH,
        budget_cap_usd=5.0,
    )
    assert session.status == SessionStatus.RUNNING

    paused = session.transition_to(SessionStatus.PAUSED_C2)
    assert paused.status == SessionStatus.PAUSED_C2

    resumed = paused.transition_to(SessionStatus.RUNNING)
    assert resumed.status == SessionStatus.RUNNING

    completed = resumed.transition_to(SessionStatus.COMPLETED)
    assert completed.status == SessionStatus.COMPLETED

    # Terminal states cannot transition back to RUNNING
    with pytest.raises(InvalidStateTransitionError):
        completed.transition_to(SessionStatus.RUNNING)

    # Test TRIPPED_BUDGET recovery lifecycle: RUNNING -> TRIPPED_BUDGET -> PAUSED_C2 -> RUNNING
    b_sess = AgentSession(
        session_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        workflow_id="wf_budget",
        agent_name="budget_agent",
        framework=AgentFramework.CREWAI,
        budget_cap_usd=1.0,
    )
    tripped_b = b_sess.transition_to(SessionStatus.TRIPPED_BUDGET)
    assert tripped_b.status == SessionStatus.TRIPPED_BUDGET

    # Operator rescues budget-tripped session via C2 pause
    paused_b = tripped_b.transition_to(SessionStatus.PAUSED_C2)
    assert paused_b.status == SessionStatus.PAUSED_C2

    resumed_b = paused_b.transition_to(SessionStatus.RUNNING)
    assert resumed_b.status == SessionStatus.RUNNING


def test_state_preset_schema() -> None:
    from argus.c2.presets import get_all_presets, get_preset

    presets = get_all_presets()
    assert len(presets) >= 4

    p = get_preset("safe-fallback-plan")
    assert p is not None
    assert p.name == "Safe Fallback Plan"
    assert len(p.patches) >= 1
    assert p.patches[0].op == "replace"


def test_argus_span_validates_hierarchy_and_timestamps() -> None:
    t0 = datetime(2026, 11, 14, 18, 0, 0, tzinfo=UTC)
    session_id = new_uuid7()
    trace_id = new_uuid7()
    root_span_id = new_uuid7()
    child_span_id = new_uuid7()

    root_order = build_dotted_order(t0, root_span_id)
    child_order = build_dotted_order(t0 + timedelta(milliseconds=10), child_span_id, root_order)

    root_span = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        trace_id=trace_id,
        span_id=root_span_id,
        parent_span_id=None,
        dotted_order=root_order,
        name="LangGraph.AgentLoop",
        span_kind=SpanKind.AGENT,
        operation_name=OperationName.INVOKE_AGENT,
        framework=AgentFramework.LANGGRAPH,
        started_at=t0,
        ended_at=t0 + timedelta(milliseconds=50),
    )
    assert root_span.span_id == root_span_id

    child_span = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        trace_id=trace_id,
        span_id=child_span_id,
        parent_span_id=root_span_id,
        dotted_order=child_order,
        name="mcp.execute_sql",
        span_kind=SpanKind.TOOL,
        operation_name=OperationName.EXECUTE_TOOL,
        framework=AgentFramework.MCP,
        started_at=t0 + timedelta(milliseconds=10),
        ended_at=t0 + timedelta(milliseconds=40),
        state_diff=(JsonPatchOp(op="replace", path="/step", value=2),),
    )
    assert child_span.parent_span_id == root_span_id

    # Mismatched parent_span_id vs dotted_order must fail validation
    with pytest.raises(ValidationError, match="dotted_order parent UUID"):
        ArgusSpan(
            tenant_id="tenant_a",
            workspace_id="ws_1",
            session_id=session_id,
            trace_id=trace_id,
            span_id=child_span_id,
            parent_span_id=new_uuid7(),
            dotted_order=child_order,
            name="invalid_parent",
            span_kind=SpanKind.TOOL,
            operation_name=OperationName.EXECUTE_TOOL,
            started_at=t0,
        )


def test_c2_override_command_and_request_digest_binding() -> None:
    pending = PendingToolCall(
        tool_call_id="call_99",
        tool_name="transfer_funds",
        tool_args={"to": "vendor_1", "amount": 500},
        is_destructive=True,
    )
    digest = pending.request_digest_sha256
    assert len(digest) == 64

    cmd = C2OverrideCommand(
        command_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=new_uuid7(),
        expected_checkpoint_id=new_uuid7(),
        operator_id="sec_ops_1",
        operator_role=Role.OPERATOR,
        action="OVERRIDE_TOOL_CALL",
        tool_override=ToolOverrideSpec(
            decision="edit",
            request_digest_sha256=digest,
            modified_args={"to": "vendor_1", "amount": 50},
        ),
        reason="Reduced transfer amount to policy limit",
    )
    assert cmd.tool_override is not None
    assert cmd.tool_override.modified_args == {"to": "vendor_1", "amount": 50}


def test_workflow_roi_attribution_calculation() -> None:
    roi = WorkflowROIAttribution.calculate(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        workflow_id="support_deflection",
        session_id=new_uuid7(),
        task_completed=True,
        task_completion_score=0.95,
        tool_correctness_score=1.0,
        llm_cost_usd=0.04,
        tool_cost_usd=0.01,
        infra_cost_usd=0.005,
        c2_intervention_cost_usd=0.0,
        wasted_loop_cost_usd=0.0,
        assigned_business_value_usd=2.20,
    )
    assert roi.total_cost_usd == pytest.approx(0.055)
    assert roi.net_roi_usd == pytest.approx(2.145)
    assert roi.roi_percentage == pytest.approx(3900.0)


def test_audit_log_entry_tamper_detection() -> None:
    session_id = new_uuid7()
    entry1 = AuditLogEntry.create_linked(
        audit_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        actor_id="op_1",
        actor_role=Role.ADMIN,
        event_type="C2_PAUSE",
        payload={"reason": "Manual inspection"},
    )
    assert entry1.verify_integrity(entry1.prev_entry_hash)

    entry2 = AuditLogEntry.create_linked(
        audit_id=new_uuid7(),
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        actor_id="op_1",
        actor_role=Role.ADMIN,
        event_type="C2_EDIT_MEMORY",
        payload={"patch": [{"op": "replace", "path": "/goal", "value": "safe"}]},
        prev_entry_hash=entry1.entry_hash,
    )
    assert entry2.verify_integrity(entry1.entry_hash)
    assert not entry2.verify_integrity("f" * 64)


def test_audit_chain_detailed_diagnostics_and_violations() -> None:
    session_id = new_uuid7()
    entry1 = AuditLogEntry.create_linked(
        audit_id=new_uuid7(),
        tenant_id="tenant_diag",
        workspace_id="ws_diag",
        session_id=session_id,
        actor_id="admin_1",
        actor_role=Role.ADMIN,
        event_type="C2_PAUSE",
        payload={"reason": "Audit review"},
    )
    # Valid genesis block
    valid, v_type, details = entry1.check_integrity_detailed(entry1.prev_entry_hash)
    assert valid is True
    assert v_type is None
    assert details is None

    # Test CHAIN_LINK_BROKEN on bad predecessor
    valid_bad_prev, v_bad_prev, details_bad = entry1.check_integrity_detailed("a" * 64)
    assert valid_bad_prev is False
    assert v_bad_prev == AuditViolationType.CHAIN_LINK_BROKEN
    assert "Chain link broken" in (details_bad or "")

    # Test PAYLOAD_DIGEST_MISMATCH: create entry with modified payload dict
    tampered_payload_entry = AuditLogEntry(
        audit_id=entry1.audit_id,
        tenant_id=entry1.tenant_id,
        workspace_id=entry1.workspace_id,
        session_id=entry1.session_id,
        actor_id=entry1.actor_id,
        actor_role=entry1.actor_role,
        event_type=entry1.event_type,
        payload={"reason": "TAMPERED_BY_ATTACKER"},
        payload_sha256=entry1.payload_sha256,
        prev_entry_hash=entry1.prev_entry_hash,
        entry_hash=entry1.entry_hash,
        created_at=entry1.created_at,
    )
    valid_pay, v_pay, details_pay = tampered_payload_entry.check_integrity_detailed(
        entry1.prev_entry_hash
    )
    assert valid_pay is False
    assert v_pay == AuditViolationType.PAYLOAD_DIGEST_MISMATCH
    assert "Payload altered" in (details_pay or "")

    # Test ENVELOPE_DIGEST_MISMATCH: modify event_type while keeping hashes intact
    tampered_env_entry = AuditLogEntry(
        audit_id=entry1.audit_id,
        tenant_id=entry1.tenant_id,
        workspace_id=entry1.workspace_id,
        session_id=entry1.session_id,
        actor_id="impersonated_actor",
        actor_role=entry1.actor_role,
        event_type=entry1.event_type,
        payload=entry1.payload,
        payload_sha256=entry1.payload_sha256,
        prev_entry_hash=entry1.prev_entry_hash,
        entry_hash=entry1.entry_hash,
        created_at=entry1.created_at,
    )
    valid_env, v_env, details_env = tampered_env_entry.check_integrity_detailed(
        entry1.prev_entry_hash
    )
    assert valid_env is False
    assert v_env == AuditViolationType.ENVELOPE_DIGEST_MISMATCH
    assert "Envelope altered" in (details_env or "")
