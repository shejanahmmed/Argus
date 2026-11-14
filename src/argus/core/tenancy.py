"""Multi-tenant security context and Role-Based Access Control (RBAC) primitives."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from argus.core.errors import AuthorizationError, TenantIsolationError


class Role(StrEnum):
    """Enterprise RBAC roles for Argus Control Plane operations."""

    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"
    INGESTOR = "INGESTOR"


_C2_MUTATION_ROLES: frozenset[Role] = frozenset({Role.OPERATOR, Role.ADMIN})


class TenantContext(BaseModel):
    """Immutable security context required by every repository port and C2 operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$")
    workspace_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$")
    actor_id: str = Field(min_length=1, max_length=128)
    role: Role = Field(default=Role.VIEWER)

    def assert_same_tenant(self, resource_tenant_id: str, resource_workspace_id: str) -> None:
        """Enforce strict tenant and workspace isolation at the domain boundary."""
        if self.tenant_id != resource_tenant_id or self.workspace_id != resource_workspace_id:
            raise TenantIsolationError(
                f"Context ({self.tenant_id}/{self.workspace_id}) cannot access "
                f"resource in ({resource_tenant_id}/{resource_workspace_id})."
            )

    def assert_can_mutate_c2(self) -> None:
        """Verify actor holds OPERATOR or ADMIN role before executing C2 interventions."""
        if self.role not in _C2_MUTATION_ROLES:
            raise AuthorizationError(
                f"Actor '{self.actor_id}' with role '{self.role}' is not authorized "
                "to execute Command & Control state mutations."
            )
