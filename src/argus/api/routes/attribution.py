"""Financial ROI attribution and Hugging Face efficiency benchmark endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.core.schemas import (
    DowngradeRecommendation,
    FleetROISummary,
    ModelBenchmarkProfile,
    SessionDowngradeReport,
    TrajectoryEvaluationReport,
    WorkflowROIAttribution,
)
from argus.core.tenancy import TenantContext

router = APIRouter(prefix="/api/v1/attribution", tags=["Attribution & Benchmarks"])


class RecommendRequest(BaseModel):
    current_model: str
    min_acceptable_accuracy: float = Field(default=0.50, ge=0.0, le=1.0)
    open_weights_only: bool = Field(default=False)


class SessionRecommendRequest(BaseModel):
    min_acceptable_accuracy: float = Field(default=0.50, ge=0.0, le=1.0)
    open_weights_only: bool = Field(default=False)
    annual_session_volume: int = Field(default=10000, ge=1)


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


@router.get("/benchmarks/catalog", response_model=list[ModelBenchmarkProfile])
async def get_benchmark_catalog(
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[ModelBenchmarkProfile]:
    """Retrieve full Hugging Face Open LLM and GAIA benchmark model profiles."""
    return container.benchmark_analyzer.catalog


@router.post("/benchmarks/catalog", response_model=ModelBenchmarkProfile)
async def register_benchmark_profile(
    profile: ModelBenchmarkProfile,
    container: Annotated[AppContainer, Depends(get_container)],
) -> ModelBenchmarkProfile:
    """Register or update a custom model benchmark profile in the catalog."""
    return container.benchmark_analyzer.register_model(profile)


@router.post("/benchmarks/recommend", response_model=list[DowngradeRecommendation])
async def recommend_model_downgrade(
    payload: RecommendRequest,
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[DowngradeRecommendation]:
    """Recommend Pareto-optimal model substitutions satisfying quality and latency constraints."""
    return container.benchmark_analyzer.get_pareto_recommendations(
        current_model_name=payload.current_model,
        min_acceptable_accuracy=payload.min_acceptable_accuracy,
        open_weights_only=payload.open_weights_only,
    )


@router.post(
    "/benchmarks/recommend-session/{session_id}",
    response_model=SessionDowngradeReport,
)
async def recommend_downgrade_for_session(
    session_id: uuid.UUID,
    payload: SessionRecommendRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> SessionDowngradeReport:
    """Analyze session spans and project dollar savings from model substitutions."""
    spans = await container.trace_store.get_session_spans(ctx, session_id)
    return container.benchmark_analyzer.analyze_session_downgrade(
        spans,
        session_id=session_id,
        min_acceptable_accuracy=payload.min_acceptable_accuracy,
        open_weights_only=payload.open_weights_only,
        annual_session_volume=payload.annual_session_volume,
    )
