"""Contract and concurrency tests for hexagonal ports and in-memory adapters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from argus.adapters_infra.in_memory import (
    InMemoryAuditStore,
    InMemoryBudgetStore,
    InMemoryControlStore,
    InMemoryEventBus,
    InMemoryTraceStore,
)
from argus.core.errors import (
    BudgetExceededError,
    CheckpointConflictError,
    TenantIsolationError,
)
from argus.core.ids import build_dotted_order, new_uuid7
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    ArgusSpan,
    CheckpointRecord,
    OperationName,
    SpanKind,
)
from argus.core.tenancy import Role, TenantContext
from argus.ports.repositories import (
    AuditStore,
    BudgetStore,
    ControlStore,
    EventBus,
    TraceStore,
)


def test_adapters_satisfy_runtime_checkable_protocols() -> None:
    assert isinstance(InMemoryTraceStore(), TraceStore)
    assert isinstance(InMemoryControlStore(), ControlStore)
    assert isinstance(InMemoryBudgetStore(), BudgetStore)
    assert isinstance(InMemoryAuditStore(), AuditStore)
    assert isinstance(InMemoryEventBus(), EventBus)


async def test_trace_store_subtree_query_and_tenant_isolation() -> None:
    store = InMemoryTraceStore()
    ctx_a = TenantContext(
        tenant_id="tenant_a", workspace_id="ws_1", actor_id="agent_1", role=Role.INGESTOR
    )
    ctx_b = TenantContext(
        tenant_id="tenant_b", workspace_id="ws_1", actor_id="agent_2", role=Role.INGESTOR
    )

    t0 = datetime(2026, 11, 14, 19, 0, 0, tzinfo=UTC)
    session_id = new_uuid7()
    trace_id = new_uuid7()
    root_id = new_uuid7()
    child_id = new_uuid7()

    root_order = build_dotted_order(t0, root_id)
    child_order = build_dotted_order(t0 + timedelta(milliseconds=5), child_id, root_order)

    root_span = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        trace_id=trace_id,
        span_id=root_id,
        parent_span_id=None,
        dotted_order=root_order,
        name="root",
        span_kind=SpanKind.AGENT,
        operation_name=OperationName.INVOKE_AGENT,
        started_at=t0,
    )
    child_span = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        trace_id=trace_id,
        span_id=child_id,
        parent_span_id=root_id,
        dotted_order=child_order,
        name="child",
        span_kind=SpanKind.LLM,
        operation_name=OperationName.CHAT,
        started_at=t0 + timedelta(milliseconds=5),
    )

    written = await store.append_spans(ctx_a, [child_span, root_span])
    assert written == 2

    # Subtree query returns spans ordered by dotted_order
    subtree = await store.get_trace_subtree(ctx_a, root_order)
    assert [s.span_id for s in subtree] == [root_id, child_id]

    # Tenant B cannot see Tenant A's trace subtree
    assert await store.get_trace_subtree(ctx_b, root_order) == []

    # Tenant B cannot append spans tagged as Tenant A
    with pytest.raises(TenantIsolationError):
        await store.append_spans(ctx_b, [root_span])


async def test_control_store_optimistic_checkpoint_concurrency_lock() -> None:
    store = InMemoryControlStore()
    ctx = TenantContext(
        tenant_id="tenant_a", workspace_id="ws_1", actor_id="op_1", role=Role.OPERATOR
    )
    session_id = new_uuid7()
    session = AgentSession(
        session_id=session_id,
        tenant_id="tenant_a",
        workspace_id="ws_1",
        workflow_id="wf_1",
        agent_name="research_agent",
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
        node_name="plan_step",
        step_index=0,
        memory_state={"messages": ["hello"]},
    )
    await store.save_checkpoint(ctx, cp1, expected_parent_id=None)

    # Saving cp2 with the correct parent (cp1.checkpoint_id) succeeds
    cp2 = CheckpointRecord(
        checkpoint_id=new_uuid7(),
        parent_checkpoint_id=cp1.checkpoint_id,
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        node_name="tool_step",
        step_index=1,
        memory_state={"messages": ["hello", "world"]},
    )
    await store.save_checkpoint(ctx, cp2, expected_parent_id=cp1.checkpoint_id)

    # A stale C2 edit referencing cp1 instead of cp2 must fail with CheckpointConflictError
    stale_cp = CheckpointRecord(
        checkpoint_id=new_uuid7(),
        parent_checkpoint_id=cp1.checkpoint_id,
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=session_id,
        node_name="stale_edit",
        step_index=1,
        memory_state={"messages": ["corrupted"]},
    )
    with pytest.raises(CheckpointConflictError):
        await store.save_checkpoint(ctx, stale_cp, expected_parent_id=cp1.checkpoint_id)


async def test_budget_store_enforces_hard_cap_atomically() -> None:
    budget = InMemoryBudgetStore()
    ctx = TenantContext(
        tenant_id="tenant_a", workspace_id="ws_1", actor_id="agent_1", role=Role.INGESTOR
    )
    session_id = new_uuid7()

    spend1 = await budget.reserve_budget(ctx, session_id, requested_usd=0.60, hard_cap_usd=1.00)
    assert spend1 == pytest.approx(0.60)

    spend2 = await budget.reserve_budget(ctx, session_id, requested_usd=0.35, hard_cap_usd=1.00)
    assert spend2 == pytest.approx(0.95)

    with pytest.raises(BudgetExceededError):
        await budget.reserve_budget(ctx, session_id, requested_usd=0.10, hard_cap_usd=1.00)

    # Spend must remain unchanged after rejected reservation
    assert await budget.get_spend(ctx, session_id) == pytest.approx(0.95)


async def test_audit_store_hash_chain_and_event_bus() -> None:
    audit = InMemoryAuditStore()
    bus = InMemoryEventBus()
    ctx = TenantContext(
        tenant_id="tenant_a", workspace_id="ws_1", actor_id="op_1", role=Role.ADMIN
    )
    session_id = new_uuid7()

    e1 = await audit.append_event(
        ctx, session_id=session_id, event_type="SESSION_START", payload={"budget": 5.0}
    )
    e2 = await audit.append_event(
        ctx, session_id=session_id, event_type="C2_OVERRIDE", payload={"tool": "sql"}
    )
    assert e2.prev_entry_hash == e1.entry_hash
    assert await audit.verify_session_chain(ctx, session_id) is True

    sub = bus.subscribe(ctx, "c2_alerts")
    await bus.publish(ctx, "c2_alerts", {"session_id": str(session_id), "state": "PAUSED_C2"})
    received = await anext(sub)
    assert received["state"] == "PAUSED_C2"
