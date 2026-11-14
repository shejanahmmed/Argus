"""Unit tests for ArgusTracer and distributed context propagation."""

from __future__ import annotations

import pytest

from argus.adapters_infra.in_memory import InMemoryTraceStore
from argus.core.ids import new_uuid7
from argus.core.schemas import OperationName, SpanKind
from argus.core.tenancy import Role, TenantContext
from argus.sdk.context import (
    get_current_dotted_order,
    get_current_session_id,
    get_current_span_id,
    get_current_trace_id,
    scope_session,
)
from argus.sdk.tracer import ArgusTracer


def test_context_scoping_maintains_ambient_state() -> None:
    session_id = new_uuid7()
    trace_id = new_uuid7()

    assert get_current_session_id() is None
    assert get_current_trace_id() is None

    with scope_session(session_id, trace_id) as snapshot:
        assert snapshot.session_id == session_id
        assert snapshot.trace_id == trace_id
        assert get_current_session_id() == session_id
        assert get_current_trace_id() == trace_id

    # Exiting context resets state cleanly
    assert get_current_session_id() is None
    assert get_current_trace_id() is None


@pytest.mark.asyncio
async def test_tracer_records_hierarchical_spans_with_timing_and_redaction() -> None:
    store = InMemoryTraceStore()
    tracer = ArgusTracer(trace_store=store)
    ctx = TenantContext(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        actor_id="test_runner",
        role=Role.OPERATOR,
    )
    session_id = new_uuid7()

    with scope_session(session_id):
        # 1. Root Agent span
        async with tracer.start_span(
            ctx,
            name="ResearchAgent",
            span_kind=SpanKind.AGENT,
            operation_name=OperationName.INVOKE_AGENT,
            input_payload={"goal": "Analyze telemetry with sk-proj-1234567890abcdefghijklmnop"},
        ) as root_builder:
            root_span_id = get_current_span_id()
            root_dotted = get_current_dotted_order()
            assert root_span_id is not None
            assert root_dotted is not None

            # 2. Child LLM span nested automatically under root
            async with tracer.start_span(
                ctx,
                name="chat:gpt-4o",
                span_kind=SpanKind.LLM,
                operation_name=OperationName.CHAT,
                model_name="gpt-4o",
            ) as llm_builder:
                llm_builder.record_tokens(
                    prompt_tokens=150,
                    completion_tokens=45,
                    cost_usd=0.002,
                    ttft_ms=120.0,
                )
                llm_builder.set_output({"content": "Analysis complete."})

            root_builder.set_output({"status": "success"})

    spans = await store.get_session_spans(ctx, session_id)
    assert len(spans) == 2

    root_span = next(s for s in spans if s.span_kind == SpanKind.AGENT)
    child_span = next(s for s in spans if s.span_kind == SpanKind.LLM)

    assert root_span.parent_span_id is None
    assert child_span.parent_span_id == root_span.span_id
    assert child_span.dotted_order.startswith(f"{root_span.dotted_order}.")

    # Confirm PII/credential scrubbing on input
    assert "[REDACTED_API_KEY]" in str(root_span.input_payload)
    assert root_span.redacted is True

    # Confirm token and cost records
    assert child_span.prompt_tokens == 150
    assert child_span.completion_tokens == 45
    assert child_span.cost_usd == pytest.approx(0.002)
    assert child_span.ttft_ms == pytest.approx(120.0)
    assert child_span.latency_ms >= 0.0
