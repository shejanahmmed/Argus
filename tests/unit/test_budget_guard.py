"""Unit tests for BudgetGuard pre-execution cost ledgering."""

from __future__ import annotations

import pytest

from argus.adapters_infra.in_memory import InMemoryBudgetStore
from argus.core.ids import new_uuid7
from argus.core.schemas import CircuitBreakerAction, CircuitBreakerReason
from argus.core.tenancy import Role, TenantContext
from argus.governance.budget_guard import BudgetGuard


@pytest.mark.asyncio
async def test_budget_guard_allows_within_cap_and_trips_when_exceeded() -> None:
    backend = InMemoryBudgetStore()
    guard = BudgetGuard(backend=backend)
    ctx = TenantContext(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        actor_id="agent_1",
        role=Role.INGESTOR,
    )
    session_id = new_uuid7()

    # Step 1: Reserve 0.40 against 1.00 cap -> ALLOW
    v1 = await guard.evaluate_and_reserve(
        ctx=ctx,
        session_id=session_id,
        requested_usd=0.40,
        hard_cap_usd=1.00,
    )
    assert not v1.tripped
    assert v1.recommended_action == CircuitBreakerAction.ALLOW
    assert v1.accumulated_cost_usd == pytest.approx(0.40)

    # Step 2: Reserve 0.50 against 1.00 cap -> ALLOW (total 0.90)
    v2 = await guard.evaluate_and_reserve(
        ctx=ctx,
        session_id=session_id,
        requested_usd=0.50,
        hard_cap_usd=1.00,
    )
    assert not v2.tripped
    assert v2.accumulated_cost_usd == pytest.approx(0.90)

    # Step 3: Reserve 0.20 against 1.00 cap -> TRIPPED (projected 1.10 > 1.00)
    v3 = await guard.evaluate_and_reserve(
        ctx=ctx,
        session_id=session_id,
        requested_usd=0.20,
        hard_cap_usd=1.00,
    )
    assert v3.tripped
    assert v3.reason == CircuitBreakerReason.BUDGET_EXCEEDED
    assert v3.recommended_action == CircuitBreakerAction.TERMINATE
    assert v3.accumulated_cost_usd == pytest.approx(0.90)

    # Current spend remains 0.90
    spend = await guard.get_current_spend(ctx, session_id)
    assert spend == pytest.approx(0.90)
