"""Attribution engine mapping LLM, tool, and infrastructure costs to task completion ROI."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from argus.attribution.evaluator import TrajectoryEvaluator
from argus.core.schemas import (
    ArgusSpan,
    FleetROISummary,
    OperationName,
    SpanKind,
    WorkflowROIAttribution,
)
from argus.core.tenancy import Role, TenantContext
from argus.ports.repositories import AuditStore, ControlStore, TraceStore


class ROIEngine:
    """Calculates financial Return on Investment (ROI) and cost attribution for agent workflows."""

    def __init__(
        self,
        trace_store: TraceStore,
        audit_store: AuditStore | None = None,
        control_store: ControlStore | None = None,
        evaluator: TrajectoryEvaluator | None = None,
        default_hourly_infra_rate_usd: float = 0.04,
        default_fixed_intervention_cost_usd: float = 0.50,
        default_tool_execution_cost_usd: float = 0.0005,
    ) -> None:
        self._store = trace_store
        self._audit_store = audit_store
        self._control_store = control_store
        self._evaluator = evaluator or TrajectoryEvaluator()
        self._default_hourly_infra_rate_usd = default_hourly_infra_rate_usd
        self._default_fixed_intervention_cost_usd = default_fixed_intervention_cost_usd
        self._default_tool_execution_cost_usd = default_tool_execution_cost_usd

    async def calculate_session_roi(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID,
        workflow_id: str = "wf_default",
        assigned_business_value_usd: float = 100.0,
        task_completed: bool | None = None,
        task_completion_score: float | None = None,
        tool_correctness_score: float | None = None,
        infra_cost_usd: float | None = None,
        c2_intervention_cost_usd: float | None = None,
        expected_tool_names: set[str] | None = None,
        goal_keywords: set[str] | None = None,
    ) -> WorkflowROIAttribution:
        """Compute verified financial ROI across all session spans and C2 interventions."""
        spans: Sequence[ArgusSpan] = await self._store.get_session_spans(ctx, session_id)

        # 1. LLM Token Inference Costs
        llm_cost = sum(
            s.cost_usd
            for s in spans
            if s.span_kind in (SpanKind.LLM, SpanKind.AGENT, SpanKind.CHAIN)
            or (s.span_kind != SpanKind.TOOL and s.cost_usd > 0.0)
        )

        # 2. Tool & MCP API Costs (dynamically extracted with configurable fallback)
        tool_cost = 0.0
        for s in spans:
            if s.span_kind == SpanKind.TOOL or s.operation_name == OperationName.EXECUTE_TOOL:
                tool_cost_attr = (
                    s.attributes.get("mcp.tool.cost_usd")
                    or s.attributes.get("argus.cost.usd")
                    or s.attributes.get("tool_cost_usd")
                )
                if tool_cost_attr is not None:
                    try:
                        tool_cost += float(tool_cost_attr)
                    except (ValueError, TypeError):
                        tool_cost += self._default_tool_execution_cost_usd
                elif s.cost_usd > 0.0:
                    tool_cost += s.cost_usd
                else:
                    tool_cost += self._default_tool_execution_cost_usd

        # 3. Container Infrastructure Compute Costs (wall-clock span duration * hourly rate)
        wall_clock_seconds = 0.0
        if spans:
            t_start = min(s.started_at for s in spans)
            t_end = max(s.ended_at or s.started_at for s in spans)
            wall_clock_seconds = max(0.0, (t_end - t_start).total_seconds())

        if infra_cost_usd is not None:
            effective_infra_cost = infra_cost_usd
        else:
            calc_infra = (wall_clock_seconds / 3600.0) * self._default_hourly_infra_rate_usd
            effective_infra_cost = (
                round(max(0.0001, calc_infra), 6) if wall_clock_seconds > 0 else 0.0001
            )

        # 4. Human Operator C2 Overhead Costs (derived from cryptographic audit events)
        c2_interventions_count = 0
        if c2_intervention_cost_usd is not None:
            effective_c2_cost = c2_intervention_cost_usd
        elif self._audit_store is not None:
            try:
                audit_entries = await self._audit_store.get_session_audit_log(ctx, session_id)
                operator_events = [
                    e
                    for e in audit_entries
                    if e.actor_role in (Role.OPERATOR, Role.ADMIN)
                    and str(e.event_type).startswith("C2_")
                ]
                c2_interventions_count = len(operator_events)
                effective_c2_cost = round(
                    c2_interventions_count * self._default_fixed_intervention_cost_usd, 4
                )
            except Exception:
                effective_c2_cost = 0.0
        else:
            effective_c2_cost = 0.0

        # 5. Wasted Loop Burn Ledgering (summing LLM and tool spend on loop spans)
        wasted_loop_cost = 0.0
        for s in spans:
            is_loop_span = (
                s.attributes.get("circuit_breaker_flag") is not None
                or s.attributes.get("is_loop_duplicate") is True
                or s.attributes.get("loop_trip") is True
            )
            if is_loop_span:
                span_cost = s.cost_usd
                if s.span_kind == SpanKind.TOOL and span_cost == 0.0:
                    span_cost = self._default_tool_execution_cost_usd
                wasted_loop_cost += span_cost

        # 6. Trajectory Evaluation Metrics
        if (
            task_completed is None
            or task_completion_score is None
            or tool_correctness_score is None
        ):
            eval_completed, eval_comp_score = self._evaluator.evaluate_task_completion(
                spans, goal_keywords
            )
            eval_tool_score = self._evaluator.evaluate_tool_correctness(
                spans, expected_tool_names or set()
            )
            final_completed = task_completed if task_completed is not None else eval_completed
            final_comp_score = (
                task_completion_score if task_completion_score is not None else eval_comp_score
            )
            final_tool_score = (
                tool_correctness_score if tool_correctness_score is not None else eval_tool_score
            )
        else:
            final_completed = task_completed
            final_comp_score = task_completion_score
            final_tool_score = tool_correctness_score

        # Default completion score to 1.0 if completed was forced True but score was 0.0
        if final_completed and final_comp_score == 0.0:
            final_comp_score = 1.0

        return WorkflowROIAttribution.calculate(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            workflow_id=workflow_id,
            session_id=session_id,
            task_completed=final_completed,
            task_completion_score=final_comp_score,
            tool_correctness_score=final_tool_score,
            llm_cost_usd=round(llm_cost, 6),
            tool_cost_usd=round(tool_cost, 6),
            infra_cost_usd=round(effective_infra_cost, 6),
            c2_intervention_cost_usd=round(effective_c2_cost, 6),
            wasted_loop_cost_usd=round(wasted_loop_cost, 6),
            assigned_business_value_usd=assigned_business_value_usd,
            wall_clock_duration_seconds=round(wall_clock_seconds, 2),
            c2_interventions_count=c2_interventions_count,
            total_spans_evaluated=len(spans),
        )

    def calculate_fleet_roi(
        self,
        ctx: TenantContext,
        sessions_roi: Sequence[WorkflowROIAttribution],
    ) -> FleetROISummary:
        """Aggregate financial ROI and performance statistics across multiple agent sessions."""
        total_sessions = len(sessions_roi)
        completed_sessions = sum(1 for s in sessions_roi if s.task_completed)
        total_fleet_spend = sum(s.total_cost_usd for s in sessions_roi)
        total_realized_value = sum(s.realized_business_value_usd for s in sessions_roi)
        net_fleet_roi = round(total_realized_value - total_fleet_spend, 6)
        fleet_roi_pct = (
            round((net_fleet_roi / total_fleet_spend) * 100.0, 4)
            if total_fleet_spend > 0.0
            else 0.0
        )
        total_wasted = sum(s.wasted_loop_cost_usd for s in sessions_roi)

        avg_comp = (
            sum(s.task_completion_score for s in sessions_roi) / total_sessions
            if total_sessions > 0
            else 0.0
        )
        avg_tool = (
            sum(s.tool_correctness_score for s in sessions_roi) / total_sessions
            if total_sessions > 0
            else 0.0
        )

        return FleetROISummary(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            total_sessions=total_sessions,
            completed_sessions=completed_sessions,
            total_fleet_spend_usd=round(total_fleet_spend, 6),
            total_realized_value_usd=round(total_realized_value, 6),
            net_fleet_roi_usd=net_fleet_roi,
            fleet_roi_percentage=fleet_roi_pct,
            total_wasted_loop_cost_usd=round(total_wasted, 6),
            average_completion_score=round(avg_comp, 4),
            average_tool_score=round(avg_tool, 4),
            sessions=list(sessions_roi),
        )
