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

    # Verify list_checkpoints chronological history
    cps = await store.list_checkpoints(ctx, session_id)
    assert len(cps) == 2
    assert [c.checkpoint_id for c in cps] == [cp1.checkpoint_id, cp2.checkpoint_id]


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

    # Release 0.40 of reservation -> Spend decreases to 0.55
    refunded = await budget.release_budget(ctx, session_id, amount_usd=0.40)
    assert refunded == pytest.approx(0.55)
    assert await budget.get_spend(ctx, session_id) == pytest.approx(0.55)

    # Now reserving 0.30 succeeds within 1.00 cap
    spend3 = await budget.reserve_budget(ctx, session_id, requested_usd=0.30, hard_cap_usd=1.00)
    assert spend3 == pytest.approx(0.85)


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


async def test_event_bus_prefix_wildcard_routing() -> None:
    bus = InMemoryEventBus()
    ctx = TenantContext(tenant_id="tenant_x", workspace_id="ws_1", actor_id="op", role=Role.ADMIN)

    # 1. Subscriber A listens on c2.*
    sub_c2 = bus.subscribe(ctx, patterns=["c2.*"])
    # 2. Subscriber B listens on telemetry.*
    sub_telem = bus.subscribe(ctx, patterns=["telemetry.*"])
    # 3. Subscriber C listens on global wildcard *
    sub_all = bus.subscribe(ctx, channel="*")

    assert bus.active_subscribers_count == 3

    # Publish C2 event
    await bus.publish(ctx, "c2.state_changed", {"session": "s1", "status": "PAUSED"})

    msg_c2 = await anext(sub_c2)
    assert msg_c2["channel"] == "c2.state_changed"
    assert msg_c2["status"] == "PAUSED"
    assert "event_id" in msg_c2

    msg_all = await anext(sub_all)
    assert msg_all["channel"] == "c2.state_changed"

    # Publish Telemetry event
    await bus.publish(ctx, "telemetry.spans", {"span_count": 5})

    msg_telem = await anext(sub_telem)
    assert msg_telem["channel"] == "telemetry.spans"
    assert msg_telem["span_count"] == 5

    msg_all_telem = await anext(sub_all)
    assert msg_all_telem["channel"] == "telemetry.spans"


async def test_event_bus_bounded_queue_drop_oldest() -> None:
    bus = InMemoryEventBus(max_queue_size=3)
    ctx = TenantContext(tenant_id="tenant_x", workspace_id="ws_1", actor_id="op", role=Role.ADMIN)

    sub = bus.subscribe(ctx, channel="test.burst")

    # Publish 5 events into a queue of size 3 without reading
    for i in range(1, 6):
        await bus.publish(ctx, "test.burst", {"seq": i})

    # The first 2 events (seq 1 and 2) must have been dropped; 3, 4, 5 must remain
    e3 = await anext(sub)
    e4 = await anext(sub)
    e5 = await anext(sub)

    assert e3["seq"] == 3
    assert e4["seq"] == 4
    assert e5["seq"] == 5


async def test_event_bus_tenant_isolation_and_diagnostics() -> None:
    bus = InMemoryEventBus()
    ctx_a = TenantContext(tenant_id="tenant_a", workspace_id="ws_1", actor_id="op", role=Role.ADMIN)
    ctx_b = TenantContext(tenant_id="tenant_b", workspace_id="ws_1", actor_id="op", role=Role.ADMIN)

    sub_a = bus.subscribe(ctx_a, channel="*")
    sub_b = bus.subscribe(ctx_b, channel="*")

    assert bus.active_subscribers_count == 2

    # Publish to Tenant A
    await bus.publish(ctx_a, "c2.event", {"target": "a_only"})

    msg_a = await anext(sub_a)
    assert msg_a["target"] == "a_only"

    # Verify bus subscriber clean-up on generator cancellation
    await sub_a.aclose()
    assert bus.active_subscribers_count == 1
    await sub_b.aclose()
    assert bus.active_subscribers_count == 0
