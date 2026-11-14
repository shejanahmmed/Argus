"""Attribution engine mapping LLM, tool, and infrastructure costs to task completion ROI."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from argus.core.schemas import ArgusSpan, WorkflowROIAttribution
from argus.core.tenancy import TenantContext
from argus.ports.repositories import TraceStore


class ROIEngine:
    """Calculates financial Return on Investment (ROI) and cost attribution for agent workflows."""

    def __init__(self, trace_store: TraceStore) -> None:
        self._store = trace_store

    async def calculate_session_roi(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID,
        workflow_id: str,
        assigned_business_value_usd: float,
        task_completed: bool,
        task_completion_score: float = 1.0,
        tool_correctness_score: float = 1.0,
        infra_cost_usd: float = 0.001,
        c2_intervention_cost_usd: float = 0.0,
    ) -> WorkflowROIAttribution:
        """Compute verified financial ROI across all session spans."""
        spans: Sequence[ArgusSpan] = await self._store.get_session_spans(ctx, session_id)

        llm_cost = sum(s.cost_usd for s in spans)
        tool_cost = sum(0.0005 for s in spans if s.span_kind.value == "TOOL")

        # Track wasted costs from repeated loop spans
        wasted_loop_cost = sum(
            s.cost_usd
            for s in spans
            if s.attributes.get("circuit_breaker_flag") is not None
        )

        return WorkflowROIAttribution.calculate(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            workflow_id=workflow_id,
            session_id=session_id,
            task_completed=task_completed,
            task_completion_score=task_completion_score,
            tool_correctness_score=tool_correctness_score,
            llm_cost_usd=llm_cost,
            tool_cost_usd=tool_cost,
            infra_cost_usd=infra_cost_usd,
            c2_intervention_cost_usd=c2_intervention_cost_usd,
            wasted_loop_cost_usd=wasted_loop_cost,
            assigned_business_value_usd=assigned_business_value_usd,
        )
