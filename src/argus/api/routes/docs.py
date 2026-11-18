"""Live /docs module configuration, publishing controls, and live presentation state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from argus.api.dependencies import get_tenant_context
from argus.core.tenancy import TenantContext

router = APIRouter(prefix="/api/v1/docs", tags=["Documentation"])


class TeamMemberInfo(BaseModel):
    """Profile data for team members showcased in /docs."""

    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=128)
    email: str = Field(default="")
    avatar_url: str = Field(default="")
    github: str = Field(default="")
    linkedin: str = Field(default="")
    bio: str = Field(default="")


class DocsConfigResponse(BaseModel):
    """Runtime publishing configuration for the live /docs module."""

    is_public: bool = True
    visibility_mode: Literal["PUBLIC", "RESTRICTED", "SCHEDULED"] = "PUBLIC"
    scheduled_start: str | None = None
    scheduled_end: str | None = None
    last_updated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    updated_by: str = "operator_admin"
    project_name: str = "Argus C2"
    tagline: str = "Zero-Tolerance Autonomous Agent Governance & Control Plane"
    team: list[TeamMemberInfo] = Field(default_factory=list)


class DocsConfigUpdateRequest(BaseModel):
    """Payload to update /docs publishing configuration and visibility."""

    is_public: bool = True
    visibility_mode: Literal["PUBLIC", "RESTRICTED", "SCHEDULED"] = "PUBLIC"
    scheduled_start: str | None = None
    scheduled_end: str | None = None
    team: list[TeamMemberInfo] | None = None


# Default in-memory configuration with lead author profile
_DEFAULT_CONFIG = DocsConfigResponse(
    is_public=True,
    visibility_mode="PUBLIC",
    scheduled_start=None,
    scheduled_end=None,
    last_updated_at=datetime.now(UTC).isoformat(),
    updated_by="operator_admin",
    project_name="Argus C2",
    tagline="Zero-Tolerance Autonomous Agent Governance & Control Plane",
    team=[
        TeamMemberInfo(
            name="Shejan Ahmmed",
            role="Lead Systems Engineer & AI Architect",
            email="shejanahmmed.dev@gmail.com",
            avatar_url="",
            github="https://github.com/ShejanAhmmed",
            linkedin="https://linkedin.com/in/shejanahmmed",
            bio=(
                "Principal architect specializing in autonomous agent governance, "
                "distributed systems resilience, and zero-spend observability architectures."
            ),
        )
    ],
)


@router.get("/config", response_model=DocsConfigResponse)
async def get_docs_config() -> DocsConfigResponse:
    """Retrieve the current live /docs publishing and visibility configuration."""
    return _DEFAULT_CONFIG


@router.post("/config", response_model=DocsConfigResponse)
async def update_docs_config(
    payload: DocsConfigUpdateRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
) -> DocsConfigResponse:
    """Update live /docs visibility, scheduling window, and team showcase."""
    _DEFAULT_CONFIG.is_public = payload.is_public
    _DEFAULT_CONFIG.visibility_mode = payload.visibility_mode
    _DEFAULT_CONFIG.scheduled_start = payload.scheduled_start
    _DEFAULT_CONFIG.scheduled_end = payload.scheduled_end
    _DEFAULT_CONFIG.last_updated_at = datetime.now(UTC).isoformat()
    _DEFAULT_CONFIG.updated_by = ctx.actor_id or "operator_admin"
    if payload.team is not None:
        _DEFAULT_CONFIG.team = payload.team
    return _DEFAULT_CONFIG
