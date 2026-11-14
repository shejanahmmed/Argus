"""Governance, automated circuit-breaker, and MCP proxy API endpoints."""

from __future__ import annotations

import contextlib
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.core.schemas import (
    CircuitBreakerAction,
    CircuitBreakerVerdict,
    PendingToolCall,
    SessionStatus,
)
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


class McpToolsListRequest(BaseModel):
    available_tools: list[dict[str, Any]] = Field(default_factory=list)


class McpInterceptRequest(BaseModel):
    session_id: uuid.UUID
    tool_call_id: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=256)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_usd: float = Field(default=0.001, ge=0.0)
    hard_cap_usd: float = Field(default=100.0, gt=0.0)


class McpInterceptResponse(BaseModel):
    verdict: CircuitBreakerVerdict
    pending_tool_call: PendingToolCall | None = None


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

    with contextlib.suppress(Exception):
        await container.control_store.add_session_cost(
            ctx, payload.session_id, payload.requested_usd
        )

    return CheckBudgetResponse(
        allowed=True,
        current_spend_usd=verdict.accumulated_cost_usd,
        remaining_usd=remaining,
        message=verdict.diagnostic_message,
    )


@router.post("/mcp/tools-list", response_model=list[dict[str, Any]])
async def filter_mcp_tools(
    payload: McpToolsListRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[dict[str, Any]]:
    """Filter MCP tools/list response according to caller's RBAC/ABAC policy."""
    return container.mcp_proxy.filter_tools_list(ctx, payload.available_tools)


@router.post("/mcp/intercept", response_model=McpInterceptResponse)
async def intercept_mcp_tool_call(
    payload: McpInterceptRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> McpInterceptResponse:
    """Intercept MCP tools/call and enforce budget, loop breaker, and HITL C2 gates."""
    verdict, pending_call = await container.mcp_proxy.intercept_tool_call(
        ctx=ctx,
        session_id=payload.session_id,
        tool_call_id=payload.tool_call_id,
        tool_name=payload.tool_name,
        tool_args=payload.tool_args,
        estimated_cost_usd=payload.estimated_cost_usd,
        hard_cap_usd=payload.hard_cap_usd,
    )

    if not verdict.tripped and payload.estimated_cost_usd > 0.0:
        with contextlib.suppress(Exception):
            await container.control_store.add_session_cost(
                ctx, payload.session_id, payload.estimated_cost_usd
            )

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
    elif (
        verdict.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2
        and pending_call is not None
    ):
        container.pending_tool_calls.setdefault(str(payload.session_id), []).append(pending_call)
        with contextlib.suppress(Exception):
            await container.control_store.transition_session(
                ctx=ctx,
                session_id=payload.session_id,
                expected_status=SessionStatus.RUNNING,
                next_status=SessionStatus.PAUSED_C2,
            )
        await container.event_bus.publish(
            ctx,
            channel="c2.intervention_required",
            event={
                "session_id": str(payload.session_id),
                "tool_call_id": pending_call.tool_call_id,
                "tool_name": pending_call.tool_name,
                "request_digest_sha256": pending_call.request_digest_sha256,
            },
        )

    return McpInterceptResponse(verdict=verdict, pending_tool_call=pending_call)


@router.post("/reset-loop/{session_id}")
async def reset_session_loop_tracker(
    session_id: uuid.UUID,
    container: Annotated[AppContainer, Depends(get_container)],
) -> dict[str, str]:
    """Clear memory tracking buffer for an agent session."""
    container.loop_detector.reset_session(str(session_id))
    return {"status": "ok", "message": f"Loop tracker cleared for session {session_id}"}
