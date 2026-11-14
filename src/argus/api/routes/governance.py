"""Governance and automated circuit-breaker API endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.core.schemas import CircuitBreakerVerdict
from argus.core.tenancy import TenantContext

router = APIRouter(prefix="/api/v1/governance", tags=["Governance"])


class CheckLoopRequest(BaseModel):
    session_id: uuid.UUID
    thought_or_content: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None


class CheckBudgetRequest(BaseModel):
    session_id: uuid.UUID
    requested_usd: float = Field(ge=0.0)
    hard_cap_usd: float = Field(gt=0.0)


class CheckBudgetResponse(BaseModel):
    allowed: bool
    current_spend_usd: float
    remaining_usd: float
    message: str


@router.post("/check-loop", response_model=CircuitBreakerVerdict)
async def check_loop(
    payload: CheckLoopRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> CircuitBreakerVerdict:
    """Evaluate whether an execution step trips the 3-Tier Loop Detector."""
    verdict = container.loop_detector.evaluate_step(
        session_id=str(payload.session_id),
        tool_name=payload.tool_name,
        tool_args=payload.tool_args,
        thought_text=payload.thought_or_content,
    )
    if verdict.tripped:
        await container.event_bus.publish(
            ctx,
            channel="governance.circuit_breaker",
            event={
                "session_id": str(payload.session_id),
                "reason": verdict.reason.value,
                "similarity_score": verdict.similarity_score,
                "repeated_count": verdict.repeated_count,
                "detail": verdict.diagnostic_message,
            },
        )
    return verdict


@router.post("/check-budget", response_model=CheckBudgetResponse)
async def check_budget(
    payload: CheckBudgetRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> CheckBudgetResponse:
    """Evaluate and atomically reserve spend against tenant hard budget caps."""
    verdict = await container.budget_guard.evaluate_and_reserve(
        ctx=ctx,
        session_id=payload.session_id,
        requested_usd=payload.requested_usd,
        hard_cap_usd=payload.hard_cap_usd,
    )
    remaining = max(0.0, payload.hard_cap_usd - verdict.accumulated_cost_usd)
    if verdict.tripped:
        await container.event_bus.publish(
            ctx,
            channel="governance.circuit_breaker",
            event={
                "session_id": str(payload.session_id),
                "reason": verdict.reason.value,
                "detail": verdict.diagnostic_message,
            },
        )
        return CheckBudgetResponse(
            allowed=False,
            current_spend_usd=verdict.accumulated_cost_usd,
            remaining_usd=0.0,
            message=verdict.diagnostic_message,
        )

    return CheckBudgetResponse(
        allowed=True,
        current_spend_usd=verdict.accumulated_cost_usd,
        remaining_usd=remaining,
        message=verdict.diagnostic_message,
    )


@router.post("/reset-loop/{session_id}")
async def reset_session_loop_tracker(
    session_id: uuid.UUID,
    container: Annotated[AppContainer, Depends(get_container)],
) -> dict[str, str]:
    """Clear memory tracking buffer for an agent session."""
    container.loop_detector.reset_session(str(session_id))
    return {"status": "ok", "message": f"Loop tracker cleared for session {session_id}"}
