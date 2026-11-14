"""Domain-level error hierarchy for Argus control, telemetry, and governance planes."""

from __future__ import annotations


class ArgusError(Exception):
    """Base exception for all structured Argus domain errors."""

    def __init__(self, message: str, *, code: str = "ARGUS_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class TenantIsolationError(ArgusError):
    """Raised when an operation attempts to access or mutate resources across tenant boundaries."""

    def __init__(self, message: str = "Cross-tenant resource access is prohibited.") -> None:
        super().__init__(message, code="TENANT_ISOLATION_VIOLATION")


class AuthorizationError(ArgusError):
    """Raised when an actor's RBAC role lacks permission for a Command & Control action."""

    def __init__(self, message: str = "Insufficient RBAC privileges for requested action.") -> None:
        super().__init__(message, code="RBAC_AUTHORIZATION_DENIED")


class InvalidStateTransitionError(ArgusError):
    """Raised when a session state transition violates the deterministic C2 state machine."""

    def __init__(self, current_state: str, target_state: str) -> None:
        super().__init__(
            f"Illegal session state transition from '{current_state}' to '{target_state}'.",
            code="INVALID_STATE_TRANSITION",
        )
        self.current_state = current_state
        self.target_state = target_state


class CheckpointConflictError(ArgusError):
    """Raised on optimistic concurrency lock failure during mid-execution C2 state edits."""

    def __init__(self, expected_id: str, actual_id: str | None) -> None:
        super().__init__(
            f"Checkpoint concurrency conflict: expected '{expected_id}', found '{actual_id}'.",
            code="CHECKPOINT_CONCURRENCY_CONFLICT",
        )
        self.expected_id = expected_id
        self.actual_id = actual_id


class BudgetExceededError(ArgusError):
    """Raised when a pre-execution budget reservation exceeds the session's hard USD cap."""

    def __init__(
        self,
        session_id: str,
        accumulated_usd: float,
        requested_usd: float,
        hard_cap_usd: float,
    ) -> None:
        super().__init__(
            f"Session '{session_id}' budget exceeded: accumulated=${accumulated_usd:.6f} "
            f"+ requested=${requested_usd:.6f} > cap=${hard_cap_usd:.6f}.",
            code="HARD_BUDGET_EXCEEDED",
        )
        self.session_id = session_id
        self.accumulated_usd = accumulated_usd
        self.requested_usd = requested_usd
        self.hard_cap_usd = hard_cap_usd


class AuditChainTamperError(ArgusError):
    """Raised when SHA-256 hash-chain verification detects a mutated or out-of-order audit log."""

    def __init__(self, message: str = "Audit log cryptographic hash chain broken.") -> None:
        super().__init__(message, code="AUDIT_CHAIN_TAMPERED")


class EntityNotFoundError(ArgusError):
    """Raised when a requested session, trace, or checkpoint does not exist in the tenant scope."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        super().__init__(
            f"{entity_type} '{entity_id}' not found in tenant scope.",
            code="ENTITY_NOT_FOUND",
        )
        self.entity_type = entity_type
        self.entity_id = entity_id
