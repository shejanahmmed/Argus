"""Unit tests for LangGraph, CrewAI, and AutoGPT framework adapters."""

from __future__ import annotations

import uuid

import pytest

from argus.adapters_infra.in_memory import InMemoryTraceStore
from argus.core.ids import new_uuid7
from argus.core.schemas import AgentFramework, SpanKind
from argus.core.tenancy import Role, TenantContext
from argus.sdk.adapters.autogpt import ArgusAutoGPTTracker
from argus.sdk.adapters.crewai import ArgusCrewAIAdapter
from argus.sdk.adapters.langgraph import ArgusLangGraphCallbackHandler
from argus.sdk.tracer import ArgusTracer


@pytest.mark.asyncio
async def test_langgraph_callback_adapter() -> None:
    store = InMemoryTraceStore()
    tracer = ArgusTracer(trace_store=store)
    ctx = TenantContext(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        actor_id="tester",
        role=Role.OPERATOR,
    )
    session_id = new_uuid7()
    handler = ArgusLangGraphCallbackHandler(tracer=tracer, ctx=ctx, session_id=session_id)

    run_id = uuid.uuid4()
    await handler.on_chain_start(
        serialized={"name": "DecisionNode"},
        inputs={"question": "What is the status?"},
        run_id=run_id,
    )

    tool_run_id = uuid.uuid4()
    await handler.on_tool_start(
        serialized={"name": "check_status"},
        input_str="device_42",
        run_id=tool_run_id,
    )
    await handler.on_tool_end(output="active", run_id=tool_run_id)

    await handler.on_chain_end(outputs={"status": "resolved"}, run_id=run_id)

    spans = await store.get_session_spans(ctx, session_id)
    assert len(spans) == 2
    chain_span = next(s for s in spans if s.span_kind == SpanKind.CHAIN)
    tool_span = next(s for s in spans if s.span_kind == SpanKind.TOOL)

    assert chain_span.framework == AgentFramework.LANGGRAPH
    assert chain_span.name == "DecisionNode"
    assert tool_span.name == "tool:check_status"
    assert tool_span.output_payload == {"output": "active"}


@pytest.mark.asyncio
async def test_crewai_adapter() -> None:
    store = InMemoryTraceStore()
    tracer = ArgusTracer(trace_store=store)
    ctx = TenantContext(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        actor_id="tester",
        role=Role.OPERATOR,
    )
    session_id = new_uuid7()
    adapter = ArgusCrewAIAdapter(tracer=tracer, ctx=ctx, session_id=session_id)

    task_id = "task_verify_infra"
    await adapter.on_task_start(
        task_id=task_id,
        agent_role="InfrastructureAuditor",
        description="Verify cluster connectivity",
    )
    await adapter.on_task_end(
        task_id=task_id,
        output="Cluster healthy",
        tokens_used=350,
        cost_usd=0.0035,
    )

    spans = await store.get_session_spans(ctx, session_id)
    assert len(spans) == 1
    span = spans[0]
    assert span.framework == AgentFramework.CREWAI
    assert span.attributes.get("crewai.agent_role") == "InfrastructureAuditor"
    assert span.completion_tokens == 350
    assert span.cost_usd == pytest.approx(0.0035)


@pytest.mark.asyncio
async def test_autogpt_tracker() -> None:
    store = InMemoryTraceStore()
    tracer = ArgusTracer(trace_store=store)
    ctx = TenantContext(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        actor_id="tester",
        role=Role.OPERATOR,
    )
    session_id = new_uuid7()
    tracker = ArgusAutoGPTTracker(tracer=tracer, ctx=ctx, session_id=session_id)

    async with tracker.track_cycle(
        cycle_number=1,
        thought="I should inspect available memory",
        plan=["Run diagnostic", "Report findings"],
    ) as builder:
        builder.set_output({"result": "16GB available"})

    spans = await store.get_session_spans(ctx, session_id)
    assert len(spans) == 1
    span = spans[0]
    assert span.framework == AgentFramework.AUTOGPT
    assert span.name == "autogpt.cycle:1"
    assert span.output_payload == {"result": "16GB available"}
