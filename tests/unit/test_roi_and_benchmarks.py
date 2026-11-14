"""Unit tests for ROI Engine, Trajectory Evaluator, and Hugging Face Benchmark Analyzer."""

from __future__ import annotations

import pytest

from argus.adapters_infra.in_memory import InMemoryTraceStore
from argus.attribution.evaluator import TrajectoryEvaluator
from argus.attribution.hf_benchmarks import HuggingFaceBenchmarkAnalyzer
from argus.attribution.roi_engine import ROIEngine
from argus.core.ids import build_dotted_order, new_uuid7, utc_now
from argus.core.schemas import AgentFramework, ArgusSpan, OperationName, SpanKind
from argus.core.tenancy import Role, TenantContext


@pytest.mark.asyncio
async def test_roi_engine_calculates_positive_and_wasted_roi() -> None:
    store = InMemoryTraceStore()
    engine = ROIEngine(trace_store=store)
    ctx = TenantContext(
        tenant_id="acme",
        workspace_id="ws1",
        actor_id="analyst",
        role=Role.VIEWER,
    )
    session_id = new_uuid7()
    t0 = utc_now()

    span_id1 = new_uuid7()
    order1 = build_dotted_order(t0, span_id1)

    span_id2 = new_uuid7()
    order2 = build_dotted_order(t0, span_id2)

    # Emitted spans
    s1 = ArgusSpan(
        tenant_id="acme",
        workspace_id="ws1",
        session_id=session_id,
        trace_id=new_uuid7(),
        span_id=span_id1,
        parent_span_id=None,
        dotted_order=order1,
        name="step1",
        span_kind=SpanKind.LLM,
        operation_name=OperationName.CHAT,
        framework=AgentFramework.LANGGRAPH,
        started_at=t0,
        cost_usd=0.04,
    )
    s2 = ArgusSpan(
        tenant_id="acme",
        workspace_id="ws1",
        session_id=session_id,
        trace_id=new_uuid7(),
        span_id=span_id2,
        parent_span_id=None,
        dotted_order=order2,
        name="step2_tool",
        span_kind=SpanKind.TOOL,
        operation_name=OperationName.EXECUTE_TOOL,
        framework=AgentFramework.LANGGRAPH,
        started_at=t0,
        cost_usd=0.01,
        attributes={"circuit_breaker_flag": "LOOP_WARNING"},
    )
    await store.append_spans(ctx, [s1, s2])

    roi = await engine.calculate_session_roi(
        ctx,
        session_id=session_id,
        workflow_id="customer_ticket_resolution",
        assigned_business_value_usd=5.00,
        task_completed=True,
    )

    assert roi.task_completed is True
    assert roi.llm_cost_usd == pytest.approx(0.05)
    assert roi.wasted_loop_cost_usd == pytest.approx(0.01)
    assert roi.assigned_business_value_usd == pytest.approx(5.00)
    assert roi.net_roi_usd > 4.90
    assert roi.roi_percentage > 9000.0


def test_trajectory_evaluator_metrics() -> None:
    evaluator = TrajectoryEvaluator()
    session_id = new_uuid7()
    t0 = utc_now()

    span_tool_id = new_uuid7()
    order_tool = build_dotted_order(t0, span_tool_id)

    span_root_id = new_uuid7()
    order_root = build_dotted_order(t0, span_root_id)

    s_tool = ArgusSpan(
        tenant_id="t1",
        workspace_id="w1",
        session_id=session_id,
        trace_id=new_uuid7(),
        span_id=span_tool_id,
        parent_span_id=None,
        dotted_order=order_tool,
        name="tool:query_database",
        span_kind=SpanKind.TOOL,
        operation_name=OperationName.EXECUTE_TOOL,
        started_at=t0,
    )
    s_root = ArgusSpan(
        tenant_id="t1",
        workspace_id="w1",
        session_id=session_id,
        trace_id=new_uuid7(),
        span_id=span_root_id,
        parent_span_id=None,
        dotted_order=order_root,
        name="agent_main",
        span_kind=SpanKind.AGENT,
        operation_name=OperationName.INVOKE_AGENT,
        started_at=t0,
        output_payload={"status": "Ticket resolved, customer refund processed successfully."},
    )

    tool_score = evaluator.evaluate_tool_correctness([s_tool], {"query_database", "send_email"})
    assert tool_score == 0.50

    completed, comp_score = evaluator.evaluate_task_completion(
        [s_tool, s_root], goal_keywords={"resolved", "refund"}
    )
    assert completed is True
    assert comp_score == 1.0


def test_hf_benchmark_pareto_recommendations() -> None:
    analyzer = HuggingFaceBenchmarkAnalyzer()

    # Evaluating candidates to replace claude-3-5-sonnet
    recs = analyzer.get_pareto_recommendations(
        "claude-3-5-sonnet", min_acceptable_accuracy=0.55
    )

    assert len(recs) >= 1
    # DeepSeek-v3 should be recommended with high cost savings
    top = recs[0]
    assert "cost_savings_pct" in top
    assert top["cost_savings_pct"] > 50.0
