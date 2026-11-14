"""Financial ROI attribution and Hugging Face efficiency benchmark endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.core.schemas import WorkflowROIAttribution
from argus.core.tenancy import TenantContext

router = APIRouter(prefix="/api/v1/attribution", tags=["Attribution & Benchmarks"])


class RecommendRequest(BaseModel):
    current_model: str
    min_acceptable_accuracy: float = Field(default=0.50, ge=0.0, le=1.0)


class BenchmarkCatalogResponse(BaseModel):
    catalog: list[dict[str, Any]]


@router.get("/roi/{session_id}", response_model=WorkflowROIAttribution)
async def get_session_roi(
    session_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
    workflow_id: str = Query(default="wf_default"),
    assigned_business_value_usd: float = Query(default=100.0, ge=0.0),
    task_completed: bool = Query(default=True),
) -> WorkflowROIAttribution:
    """Calculate token financial attribution, exact costs, and net ROI for an agent session."""
    return await container.roi_engine.calculate_session_roi(
        ctx=ctx,
        session_id=session_id,
        workflow_id=workflow_id,
        assigned_business_value_usd=assigned_business_value_usd,
        task_completed=task_completed,
    )


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
