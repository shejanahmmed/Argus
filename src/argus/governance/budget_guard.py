"""Pre-execution hard budget guard for autonomous agent sessions.

Enforces zero budget depletion by reserving and validating requested LLM/tool cost
against the session's hard cap before allowing model or tool execution to proceed.
Includes dynamic token-to-USD normalization, soft warning thresholds, and refund reconciliation.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol, runtime_checkable

from argus.core.errors import BudgetExceededError
from argus.core.pricing import estimate_token_cost_usd
from argus.core.schemas import (
    CircuitBreakerAction,
    CircuitBreakerReason,
    CircuitBreakerVerdict,
)
from argus.core.tenancy import TenantContext


@runtime_checkable
class BudgetBackend(Protocol):
    """Protocol for budget storage backend (e.g., in-memory or SQLite/Redis)."""

    async def reserve_budget(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        requested_usd: float,
        hard_cap_usd: float,
    ) -> float:
        ...

    async def release_budget(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        amount_usd: float,
    ) -> float:
        ...

    async def get_spend(self, ctx: TenantContext, session_id: uuid.UUID) -> float:
        ...


class BudgetGuard:
    """Pre-execution budget enforcement engine preventing financial runaway loops."""

    def __init__(
        self,
        backend: BudgetBackend,
        *,
        warning_threshold: float = 0.80,
    ) -> None:
        self._backend = backend
        self._warning_threshold = max(0.01, min(0.99, warning_threshold))
        self._lock = asyncio.Lock()

    async def evaluate_and_reserve(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        requested_usd: float = 0.0,
        hard_cap_usd: float = 50.0,
        *,
        model_name: str | None = None,
        estimated_prompt_tokens: int = 0,
        estimated_completion_tokens: int = 0,
    ) -> CircuitBreakerVerdict:
        """Atomically evaluate requested spend against the hard cap.

        If requested_usd is 0.0 and model_name is provided, dynamically resolves
        the estimated cost from the token pricing catalog.
        """
        effective_usd = requested_usd
        if effective_usd <= 0.0 and model_name:
            effective_usd = estimate_token_cost_usd(
                model_name,
                estimated_prompt_tokens,
                estimated_completion_tokens,
            )

        if effective_usd < 0.0:
            raise ValueError("effective requested cost cannot be negative.")
        if hard_cap_usd <= 0.0:
            raise ValueError("hard_cap_usd must be positive.")

        try:
            new_spend = await self._backend.reserve_budget(
                ctx=ctx,
                session_id=session_id,
                requested_usd=effective_usd,
                hard_cap_usd=hard_cap_usd,
            )
            utilization = new_spend / hard_cap_usd
            if utilization >= self._warning_threshold:
                diagnostic = (
                    f"Budget warning: spend ${new_spend:.6f} / ${hard_cap_usd:.6f} "
                    f"({utilization * 100:.1f}%) reached proactive threshold "
                    f"({self._warning_threshold * 100:.0f}%)."
                )
            else:
                diagnostic = f"Budget reserved: ${new_spend:.6f} / ${hard_cap_usd:.6f}"

            return CircuitBreakerVerdict(
                tripped=False,
                reason=CircuitBreakerReason.NONE,
                similarity_score=0.0,
                repeated_count=0,
                accumulated_cost_usd=new_spend,
                budget_limit_usd=hard_cap_usd,
                wasted_cost_usd=0.0,
                recommended_action=CircuitBreakerAction.ALLOW,
                diagnostic_message=diagnostic,
            )
        except BudgetExceededError as err:
            return CircuitBreakerVerdict(
                tripped=True,
                trip_tier=None,
                reason=CircuitBreakerReason.BUDGET_EXCEEDED,
                similarity_score=0.0,
                repeated_count=0,
                accumulated_cost_usd=err.accumulated_usd,
                budget_limit_usd=err.hard_cap_usd,
                wasted_cost_usd=0.0,
                recommended_action=CircuitBreakerAction.TERMINATE,
                diagnostic_message=(
                    f"Hard budget exceeded: current=${err.accumulated_usd:.6f} + "
                    f"requested=${err.requested_usd:.6f} > cap=${err.hard_cap_usd:.6f}."
                ),
            )

    async def release_reservation(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        amount_usd: float,
    ) -> float:
        """Refund or reconcile over-reserved spend."""
        return await self._backend.release_budget(ctx, session_id, amount_usd)

    async def get_current_spend(self, ctx: TenantContext, session_id: uuid.UUID) -> float:
        """Retrieve total accumulated spend for a given session."""
        return await self._backend.get_spend(ctx, session_id)


__all__ = [
    "BudgetBackend",
    "BudgetGuard",
]
