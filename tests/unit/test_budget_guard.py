"""Unit tests for BudgetGuard pre-execution cost ledgering and dynamic token normalization."""

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


@pytest.mark.asyncio
async def test_budget_guard_dynamic_token_normalization() -> None:
    backend = InMemoryBudgetStore()
    guard = BudgetGuard(backend=backend)
    ctx = TenantContext(
        tenant_id="tenant_pricing",
        workspace_id="ws_pricing",
        actor_id="worker_llm",
        role=Role.INGESTOR,
    )
    session_id = new_uuid7()

    # Model: Claude 3.5 Sonnet ($3.00 input, $15.00 output per 1M tokens)
    # 1,000 prompt tokens = $0.003
    # 500 completion tokens = $0.0075
    # Total expected: $0.0105
    verdict = await guard.evaluate_and_reserve(
        ctx=ctx,
        session_id=session_id,
        requested_usd=0.0,
        hard_cap_usd=5.00,
        model_name="claude-3-5-sonnet-20241022",
        estimated_prompt_tokens=1000,
        estimated_completion_tokens=500,
    )
    assert not verdict.tripped
    assert verdict.recommended_action == CircuitBreakerAction.ALLOW
    assert verdict.accumulated_cost_usd == pytest.approx(0.0105, abs=1e-5)


@pytest.mark.asyncio
async def test_budget_guard_soft_warning_threshold() -> None:
    backend = InMemoryBudgetStore()
    guard = BudgetGuard(backend=backend, warning_threshold=0.80)
    ctx = TenantContext(
        tenant_id="tenant_warn",
        workspace_id="ws_warn",
        actor_id="worker_warn",
        role=Role.INGESTOR,
    )
    session_id = new_uuid7()

    # Step 1: 0.70 of 1.00 (70%) -> Under 80% threshold
    v1 = await guard.evaluate_and_reserve(
        ctx=ctx,
        session_id=session_id,
        requested_usd=0.70,
        hard_cap_usd=1.00,
    )
    assert not v1.tripped
    assert "Budget warning" not in v1.diagnostic_message

    # Step 2: Additional 0.15 (total 0.85 = 85%) -> Exceeds 80% warning threshold but ALLOWED
    v2 = await guard.evaluate_and_reserve(
        ctx=ctx,
        session_id=session_id,
        requested_usd=0.15,
        hard_cap_usd=1.00,
    )
    assert not v2.tripped
    assert v2.recommended_action == CircuitBreakerAction.ALLOW
    assert "Budget warning" in v2.diagnostic_message
    assert "85.0%" in v2.diagnostic_message


@pytest.mark.asyncio
async def test_budget_guard_release_reservation() -> None:
    backend = InMemoryBudgetStore()
    guard = BudgetGuard(backend=backend)
    ctx = TenantContext(
        tenant_id="tenant_refund",
        workspace_id="ws_refund",
        actor_id="worker_refund",
        role=Role.OPERATOR,
    )
    session_id = new_uuid7()

    # Reserve 0.50
    await guard.evaluate_and_reserve(
        ctx=ctx,
        session_id=session_id,
        requested_usd=0.50,
        hard_cap_usd=1.00,
    )
    spend_before = await guard.get_current_spend(ctx, session_id)
    assert spend_before == pytest.approx(0.50)

    # Release/Refund 0.30 of unused reservation
    spend_after = await guard.release_reservation(ctx, session_id, amount_usd=0.30)
    assert spend_after == pytest.approx(0.20)

    current_spend = await guard.get_current_spend(ctx, session_id)
    assert current_spend == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_budget_guard_multi_tenant_isolation() -> None:
    backend = InMemoryBudgetStore()
    guard = BudgetGuard(backend=backend)
    session_id = new_uuid7()

    ctx_a = TenantContext(
        tenant_id="tenant_alpha",
        workspace_id="prod",
        actor_id="actor_a",
        role=Role.INGESTOR,
    )
    ctx_b = TenantContext(
        tenant_id="tenant_beta",
        workspace_id="prod",
        actor_id="actor_b",
        role=Role.INGESTOR,
    )

    # Tenant Alpha spends 0.90 of 1.00
    await guard.evaluate_and_reserve(
        ctx=ctx_a,
        session_id=session_id,
        requested_usd=0.90,
        hard_cap_usd=1.00,
    )

    # Tenant Beta should have 0.00 spend and be able to reserve 0.90 without tripping
    spend_b = await guard.get_current_spend(ctx_b, session_id)
    assert spend_b == pytest.approx(0.0)

    v_b = await guard.evaluate_and_reserve(
        ctx=ctx_b,
        session_id=session_id,
        requested_usd=0.90,
        hard_cap_usd=1.00,
    )
    assert not v_b.tripped
    assert v_b.accumulated_cost_usd == pytest.approx(0.90)
