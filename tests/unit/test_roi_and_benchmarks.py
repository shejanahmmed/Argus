"""Unit tests for ROI Engine, Trajectory Evaluator, and Hugging Face Benchmark Analyzer."""

from __future__ import annotations

import datetime

import pytest

from argus.adapters_infra.in_memory import InMemoryAuditStore, InMemoryTraceStore
from argus.attribution.evaluator import TrajectoryEvaluator
from argus.attribution.hf_benchmarks import HuggingFaceBenchmarkAnalyzer
from argus.attribution.roi_engine import ROIEngine
from argus.core.ids import build_dotted_order, new_uuid7, utc_now
from argus.core.schemas import (
    AgentFramework,
    ArgusSpan,
    ModelBenchmarkProfile,
    OperationName,
    SpanKind,
)
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
    assert roi.llm_cost_usd == pytest.approx(0.04)
    assert roi.tool_cost_usd == pytest.approx(0.01)
    assert roi.wasted_loop_cost_usd == pytest.approx(0.01)
    assert roi.assigned_business_value_usd == pytest.approx(5.00)
    assert roi.realized_business_value_usd == pytest.approx(5.00)
    assert roi.net_roi_usd > 4.90
    assert roi.roi_percentage > 9000.0


@pytest.mark.asyncio
async def test_roi_engine_four_categories_with_audit_and_infra() -> None:
    trace_store = InMemoryTraceStore()
    audit_store = InMemoryAuditStore()
    engine = ROIEngine(
        trace_store=trace_store,
        audit_store=audit_store,
        default_hourly_infra_rate_usd=0.04,
        default_fixed_intervention_cost_usd=0.50,
    )
    ctx = TenantContext(
        tenant_id="acme",
        workspace_id="ws1",
        actor_id="analyst",
        role=Role.OPERATOR,
    )
    session_id = new_uuid7()
    t0 = utc_now()
    t1 = t0 + datetime.timedelta(seconds=120)

    span_id1 = new_uuid7()
    order1 = build_dotted_order(t0, span_id1)

    span_id2 = new_uuid7()
    order2 = build_dotted_order(t0, span_id2)

    # 1. LLM span
    s1 = ArgusSpan(
        tenant_id="acme",
        workspace_id="ws1",
        session_id=session_id,
        trace_id=new_uuid7(),
        span_id=span_id1,
        parent_span_id=None,
        dotted_order=order1,
        name="llm_reasoning",
        span_kind=SpanKind.LLM,
        operation_name=OperationName.CHAT,
        started_at=t0,
        ended_at=t0 + datetime.timedelta(seconds=2),
        cost_usd=0.05,
    )
    # 2. Tool span with custom dynamic tool cost attribute
    s2 = ArgusSpan(
        tenant_id="acme",
        workspace_id="ws1",
        session_id=session_id,
        trace_id=new_uuid7(),
        span_id=span_id2,
        parent_span_id=None,
        dotted_order=order2,
        name="tool:query_stripe_api",
        span_kind=SpanKind.TOOL,
        operation_name=OperationName.EXECUTE_TOOL,
        started_at=t0 + datetime.timedelta(seconds=5),
        ended_at=t1,
        attributes={"mcp.tool.cost_usd": "0.0035"},
    )
    await trace_store.append_spans(ctx, [s1, s2])

    # 3. Append operator audit interventions
    await audit_store.append_event(
        ctx,
        session_id=session_id,
        event_type="C2_PAUSE",
        payload={"reason": "Manual review required"},
    )
    await audit_store.append_event(
        ctx,
        session_id=session_id,
        event_type="C2_OVERRIDE_TOOL_CALL",
        payload={"decision": "APPROVE"},
    )

    roi = await engine.calculate_session_roi(
        ctx,
        session_id=session_id,
        workflow_id="stripe_dispute_resolution",
        assigned_business_value_usd=100.0,
        task_completed=True,
    )

    # Assert 4 granular cost categories
    assert roi.llm_cost_usd == pytest.approx(0.05)
    assert roi.tool_cost_usd == pytest.approx(0.0035)
    # Infra cost: 120s / 3600s * $0.04/hr = ~$0.001333
    assert roi.infra_cost_usd == pytest.approx(0.001333, rel=1e-3)
    # C2 intervention cost: 2 interventions * $0.50 = $1.00
    assert roi.c2_intervention_cost_usd == pytest.approx(1.00)
    assert roi.c2_interventions_count == 2
    assert roi.wall_clock_duration_seconds == pytest.approx(120.0, rel=1e-2)
    assert roi.total_spans_evaluated == 2

    # Total cost = 0.05 + 0.0035 + 0.001333 + 1.00 = ~1.054833
    expected_total = 0.05 + 0.0035 + 0.001333 + 1.00
    assert roi.total_cost_usd == pytest.approx(expected_total, rel=1e-3)
    assert roi.net_roi_usd == pytest.approx(100.0 - expected_total, rel=1e-3)


def test_trajectory_evaluator_deep_report() -> None:
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

    report = evaluator.evaluate_trajectory(
        [s_tool, s_root],
        tenant_id="t1",
        workspace_id="w1",
        session_id=session_id,
        expected_tool_names={"query_database", "send_email"},
        goal_keywords={"resolved", "refund"},
    )

    assert report.total_steps == 2
    assert report.tool_steps == 1
    assert report.llm_steps == 1
    assert report.matched_tools == ["query_database"]
    assert report.missing_tools == ["send_email"]
    assert report.unexpected_tools == []
    assert report.tool_correctness_score == 0.50
    assert report.task_completed is True
    assert report.task_completion_score == 1.0
    assert report.fatal_errors_detected == []
    assert "completed successfully" in report.diagnostic_summary.lower()


def test_trajectory_evaluator_detects_fatal_errors() -> None:
    evaluator = TrajectoryEvaluator()
    session_id = new_uuid7()
    t0 = utc_now()

    span_err_id = new_uuid7()
    order_err = build_dotted_order(t0, span_err_id)

    s_err = ArgusSpan(
        tenant_id="t1",
        workspace_id="w1",
        session_id=session_id,
        trace_id=new_uuid7(),
        span_id=span_err_id,
        parent_span_id=None,
        dotted_order=order_err,
        name="tool:execute_sql",
        span_kind=SpanKind.TOOL,
        operation_name=OperationName.EXECUTE_TOOL,
        started_at=t0,
        attributes={"status": "error"},
        output_payload={"exception": "DatabaseConnectionRefused", "failed": True},
    )

    report = evaluator.evaluate_trajectory(
        [s_err],
        tenant_id="t1",
        workspace_id="w1",
        session_id=session_id,
        expected_tool_names={"execute_sql"},
        goal_keywords={"confirmed"},
    )

    assert report.task_completed is False
    assert report.task_completion_score == 0.0
    assert len(report.fatal_errors_detected) >= 1
    assert "failed" in report.diagnostic_summary.lower()


def test_fleet_roi_summary_aggregation() -> None:
    store = InMemoryTraceStore()
    engine = ROIEngine(trace_store=store)
    ctx = TenantContext(
        tenant_id="t1",
        workspace_id="w1",
        actor_id="admin",
        role=Role.ADMIN,
    )

    roi1 = engine.calculate_fleet_roi(
        ctx,
        [],
    )
    assert roi1.total_sessions == 0
    assert roi1.total_fleet_spend_usd == 0.0

    from argus.core.schemas import WorkflowROIAttribution

    r1 = WorkflowROIAttribution.calculate(
        tenant_id="t1",
        workspace_id="w1",
        workflow_id="wf1",
        session_id=new_uuid7(),
        task_completed=True,
        task_completion_score=1.0,
        tool_correctness_score=1.0,
        llm_cost_usd=0.10,
        tool_cost_usd=0.01,
        infra_cost_usd=0.005,
        c2_intervention_cost_usd=0.50,
        wasted_loop_cost_usd=0.02,
        assigned_business_value_usd=10.0,
    )
    r2 = WorkflowROIAttribution.calculate(
        tenant_id="t1",
        workspace_id="w1",
        workflow_id="wf2",
        session_id=new_uuid7(),
        task_completed=False,
        task_completion_score=0.40,
        tool_correctness_score=0.50,
        llm_cost_usd=0.20,
        tool_cost_usd=0.02,
        infra_cost_usd=0.01,
        c2_intervention_cost_usd=0.0,
        wasted_loop_cost_usd=0.05,
        assigned_business_value_usd=20.0,
    )

    fleet = engine.calculate_fleet_roi(ctx, [r1, r2])
    assert fleet.total_sessions == 2
    assert fleet.completed_sessions == 1
    # r1 total cost = 0.10 + 0.01 + 0.005 + 0.50 = 0.615
    # r2 total cost = 0.20 + 0.02 + 0.01 = 0.23
    assert fleet.total_fleet_spend_usd == pytest.approx(0.845)
    # r1 realized = 10.0 * 1.0 = 10.0
    # r2 realized = 0.0 (task_completed is False)
    assert fleet.total_realized_value_usd == pytest.approx(10.0)
    assert fleet.net_fleet_roi_usd == pytest.approx(10.0 - 0.845)
    assert fleet.total_wasted_loop_cost_usd == pytest.approx(0.07)
    assert fleet.average_completion_score == pytest.approx(0.70)
    assert fleet.average_tool_score == pytest.approx(0.75)


def test_hf_benchmark_pareto_recommendations() -> None:
    analyzer = HuggingFaceBenchmarkAnalyzer()

    # Evaluating candidates to replace claude-3-5-sonnet
    recs = analyzer.get_pareto_recommendations(
        "claude-3-5-sonnet", min_acceptable_accuracy=0.55
    )

    assert len(recs) >= 1
    # Recommendations should include DeepSeek-v3 or Llama-3.3-70b
    candidate_names = [r.candidate_model for r in recs]
    assert "deepseek-v3" in candidate_names or "llama-3-3-70b" in candidate_names
    top = recs[0]
    assert top.cost_savings_pct > 50.0
    assert top.is_pareto_optimal is True
    assert top.strategy_tier in (
        "EXTREME_SAVINGS",
        "BALANCED_FRONTIER",
        "ULTRA_LOW_LATENCY",
        "OPEN_WEIGHTS_PREFERRED",
    )


def test_hf_benchmark_alias_resolution() -> None:
    analyzer = HuggingFaceBenchmarkAnalyzer()

    # Resolve provider aliases
    p1 = analyzer.resolve_model("claude-3-5-sonnet-20241022")
    assert p1 is not None
    assert p1.model_name == "claude-3-5-sonnet"

    p2 = analyzer.resolve_model("meta-llama/llama-3.3-70b-instruct")
    assert p2 is not None
    assert p2.model_name == "llama-3-3-70b"

    p3 = analyzer.resolve_model("unknown-custom-model-xyz")
    assert p3 is None


def test_hf_benchmark_open_weights_filtering() -> None:
    analyzer = HuggingFaceBenchmarkAnalyzer()

    # Recommend only open-weights candidates
    recs = analyzer.get_pareto_recommendations(
        "gpt-4o", min_acceptable_accuracy=0.50, open_weights_only=True
    )

    assert len(recs) >= 1
    for r in recs:
        assert r.open_weights is True


def test_hf_benchmark_custom_catalog_registration() -> None:
    analyzer = HuggingFaceBenchmarkAnalyzer()

    custom = ModelBenchmarkProfile(
        model_name="qwen-2-5-coder-32b-local",
        display_name="Qwen 2.5 Coder 32B (Local vLLM)",
        provider="self-hosted",
        open_weights=True,
        gaia_accuracy=0.65,
        open_llm_score=78.0,
        ttft_ms=120.0,
        throughput_tokens_sec=110.0,
        input_cost_per_1k=0.00005,
        output_cost_per_1k=0.00010,
        context_window_tokens=128000,
        aliases=("qwen-coder-local",),
    )
    registered = analyzer.register_model(custom)
    assert registered.model_name == "qwen-2-5-coder-32b-local"

    recs = analyzer.get_pareto_recommendations(
        "claude-3-5-sonnet", min_acceptable_accuracy=0.60
    )
    assert any(r.candidate_model == "qwen-2-5-coder-32b-local" for r in recs)


def test_hf_benchmark_session_downgrade_analysis() -> None:
    analyzer = HuggingFaceBenchmarkAnalyzer()
    session_id = new_uuid7()
    t0 = utc_now()

    span_id = new_uuid7()
    s = ArgusSpan(
        tenant_id="t1",
        workspace_id="w1",
        session_id=session_id,
        trace_id=new_uuid7(),
        span_id=span_id,
        parent_span_id=None,
        dotted_order=build_dotted_order(t0, span_id),
        name="llm_chat",
        span_kind=SpanKind.LLM,
        operation_name=OperationName.CHAT,
        model_name="claude-3-5-sonnet",
        prompt_tokens=8000,
        completion_tokens=2500,
        cost_usd=0.0615,
        started_at=t0,
    )

    report = analyzer.analyze_session_downgrade(
        [s],
        session_id=session_id,
        min_acceptable_accuracy=0.55,
        annual_session_volume=5000,
    )

    assert report.session_id == session_id
    assert report.active_model == "claude-3-5-sonnet"
    assert report.total_prompt_tokens == 8000
    assert report.total_completion_tokens == 2500
    assert report.current_session_cost_usd > 0.05
    assert len(report.recommendations) >= 1

    top = report.recommendations[0]
    assert top.projected_session_cost_usd < report.current_session_cost_usd
    assert top.session_dollar_savings_usd > 0.0
    assert top.projected_annual_savings_10k_sessions_usd > 0.0
