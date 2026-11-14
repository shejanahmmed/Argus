"""Pre-execution hard budget guard for autonomous agent sessions.

Enforces zero budget depletion by reserving and validating requested LLM/tool cost
against the session's hard cap before allowing model or tool execution to proceed.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol, runtime_checkable

from argus.core.errors import BudgetExceededError
from argus.core.schemas import (
    CircuitBreakerAction,
    CircuitBreakerReason,
    CircuitBreakerVerdict,
)
from argus.core.tenancy import TenantContext


@runtime_checkable
class BudgetBackend(Protocol):
    """Protocol for budget storage backend (e.g., in-memory or Redis Lua)."""

    async def reserve_budget(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        requested_usd: float,
        hard_cap_usd: float,
    ) -> float:
        ...

    async def get_spend(self, ctx: TenantContext, session_id: uuid.UUID) -> float:
        ...


class BudgetGuard:
    """Pre-execution budget enforcement engine preventing financial runaway loops."""

    def __init__(self, backend: BudgetBackend) -> None:
        self._backend = backend
        self._lock = asyncio.Lock()

    async def evaluate_and_reserve(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        requested_usd: float,
        hard_cap_usd: float,
    ) -> CircuitBreakerVerdict:
        """Atomically evaluate requested spend against the hard cap.

        If the projected spend exceeds hard_cap_usd, trips the circuit breaker with
        BUDGET_EXCEEDED and TERMINATE recommendation.
        """
        if requested_usd < 0.0:
            raise ValueError("requested_usd cannot be negative.")
        if hard_cap_usd <= 0.0:
            raise ValueError("hard_cap_usd must be positive.")

        try:
            new_spend = await self._backend.reserve_budget(
                ctx=ctx,
                session_id=session_id,
                requested_usd=requested_usd,
                hard_cap_usd=hard_cap_usd,
            )
            return CircuitBreakerVerdict(
                tripped=False,
                reason=CircuitBreakerReason.NONE,
                similarity_score=0.0,
                repeated_count=0,
                accumulated_cost_usd=new_spend,
                budget_limit_usd=hard_cap_usd,
                recommended_action=CircuitBreakerAction.ALLOW,
                diagnostic_message=f"Budget reserved: ${new_spend:.6f} / ${hard_cap_usd:.6f}",
            )
        except BudgetExceededError as err:
            return CircuitBreakerVerdict(
                tripped=True,
                reason=CircuitBreakerReason.BUDGET_EXCEEDED,
                similarity_score=0.0,
                repeated_count=0,
                accumulated_cost_usd=err.accumulated_usd,
                budget_limit_usd=err.hard_cap_usd,
                recommended_action=CircuitBreakerAction.TERMINATE,
                diagnostic_message=(
                    f"Hard budget exceeded: current=${err.accumulated_usd:.6f} + "
                    f"requested=${err.requested_usd:.6f} > cap=${err.hard_cap_usd:.6f}."
                ),
            )

    async def get_current_spend(self, ctx: TenantContext, session_id: uuid.UUID) -> float:
        """Retrieve total accumulated spend for a given session."""
        return await self._backend.get_spend(ctx, session_id)
