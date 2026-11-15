"""Financial ROI attribution and Hugging Face efficiency benchmark endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.core.schemas import (
    FleetROISummary,
    TrajectoryEvaluationReport,
    WorkflowROIAttribution,
)
from argus.core.tenancy import TenantContext

router = APIRouter(prefix="/api/v1/attribution", tags=["Attribution & Benchmarks"])


class RecommendRequest(BaseModel):
    current_model: str
    min_acceptable_accuracy: float = Field(default=0.50, ge=0.0, le=1.0)


class TrajectoryEvaluationRequest(BaseModel):
    expected_tools: list[str] = Field(default_factory=list)
    goal_keywords: list[str] = Field(default_factory=list)


@router.get("/roi/{session_id}", response_model=WorkflowROIAttribution)
async def get_session_roi(
    session_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
    workflow_id: str = Query(default="wf_default"),
    assigned_business_value_usd: float = Query(default=100.0, ge=0.0),
    task_completed: bool | None = Query(default=None),
    infra_cost_usd: float | None = Query(default=None, ge=0.0),
    c2_intervention_cost_usd: float | None = Query(default=None, ge=0.0),
) -> WorkflowROIAttribution:
    """Calculate token financial attribution, 4-bucket costs, and net ROI for an agent session."""
    return await container.roi_engine.calculate_session_roi(
        ctx=ctx,
        session_id=session_id,
        workflow_id=workflow_id,
        assigned_business_value_usd=assigned_business_value_usd,
        task_completed=task_completed,
        infra_cost_usd=infra_cost_usd,
        c2_intervention_cost_usd=c2_intervention_cost_usd,
    )


@router.post("/evaluate/{session_id}", response_model=TrajectoryEvaluationReport)
async def evaluate_session_trajectory(
    session_id: uuid.UUID,
    payload: TrajectoryEvaluationRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> TrajectoryEvaluationReport:
    """Run deterministic trajectory evaluation analyzing tools, keywords, errors, and goals."""
    spans = await container.trace_store.get_session_spans(ctx, session_id)
    return container.trajectory_evaluator.evaluate_trajectory(
        spans,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        expected_tool_names=set(payload.expected_tools) if payload.expected_tools else None,
        goal_keywords=set(payload.goal_keywords) if payload.goal_keywords else None,
    )


@router.get("/fleet-roi", response_model=FleetROISummary)
async def get_fleet_roi_summary(
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
    default_task_value_usd: float = Query(default=100.0, ge=0.0),
) -> FleetROISummary:
    """Aggregate fleet-wide ROI attribution, wasted loop burn, and performance metrics."""
    sessions = await container.control_store.list_sessions(ctx)
    rois: list[WorkflowROIAttribution] = []
    for s in sessions:
        roi = await container.roi_engine.calculate_session_roi(
            ctx=ctx,
            session_id=s.session_id,
            workflow_id=s.workflow_id,
            assigned_business_value_usd=default_task_value_usd,
        )
        rois.append(roi)

    return container.roi_engine.calculate_fleet_roi(ctx, rois)


@router.get("/benchmarks/catalog", response_model=list[dict[str, Any]])
async def get_benchmark_catalog(
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[dict[str, Any]]:
    """Retrieve full Hugging Face baseline benchmark model profiles."""
    return [
        {
            "model_name": m.model_name,
            "provider": m.provider,
            "gaia_accuracy": m.gaia_accuracy,
            "ttft_ms": m.ttft_ms,
            "throughput_tokens_sec": m.throughput_tokens_sec,
            "input_cost_per_1k": m.input_cost_per_1k,
            "output_cost_per_1k": m.output_cost_per_1k,
        }
        for m in container.benchmark_analyzer._catalog
    ]


@router.post("/benchmarks/recommend", response_model=list[dict[str, Any]])
async def recommend_model_downgrade(
    payload: RecommendRequest,
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[dict[str, Any]]:
    """Recommend high-efficiency model substitutions satisfying minimum quality constraints."""
    return container.benchmark_analyzer.get_pareto_recommendations(
        current_model_name=payload.current_model,
        min_acceptable_accuracy=payload.min_acceptable_accuracy,
    )
