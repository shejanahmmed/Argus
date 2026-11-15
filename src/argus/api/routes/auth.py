"""Security and Token Management routes for Argus Control Plane."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, status

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.core.schemas import IssueTokenRequest, IssueTokenResponse
from argus.core.tenancy import TenantContext

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Security"])


@router.post(
    "/tokens",
    response_model=IssueTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue an HMAC-SHA256 Bearer Token for an agent worker or operator.",
)
async def issue_token_endpoint(
    req: IssueTokenRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> IssueTokenResponse:
    """Issue a cryptographically signed HMAC-SHA256 Bearer token.

    Enforces that caller holds ADMIN privileges and can only issue tokens
    within their own tenant and workspace boundaries.
    """
    ctx.assert_can_issue_tokens()
    ctx.assert_same_tenant(req.tenant_id, req.workspace_id)

    target_ctx = TenantContext(
        tenant_id=req.tenant_id,
        workspace_id=req.workspace_id,
        actor_id=req.actor_id,
        role=req.role,
    )

    now_epoch = int(time.time())
    token = container.authenticator.issue_token(
        target_ctx,
        ttl_seconds=req.ttl_seconds,
        now_epoch=now_epoch,
    )

    return IssueTokenResponse(
        token=token,
        tenant_id=req.tenant_id,
        workspace_id=req.workspace_id,
        actor_id=req.actor_id,
        role=req.role,
        expires_at_epoch=now_epoch + req.ttl_seconds,
    )


@router.get(
    "/me",
    summary="Inspect the authenticated TenantContext claims of the current caller.",
)
async def get_current_actor_claims(
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, str]:
    """Return the active security context verified from the Bearer token."""
    return {
        "tenant_id": ctx.tenant_id,
        "workspace_id": ctx.workspace_id,
        "actor_id": ctx.actor_id,
        "role": ctx.role.value,
    }
