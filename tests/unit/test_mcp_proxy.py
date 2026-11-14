"""Unit tests for Model Context Protocol (MCP) JSON-RPC Governance Proxy."""

from __future__ import annotations

import pytest

from argus.adapters_infra.in_memory import InMemoryBudgetStore
from argus.core.ids import new_uuid7
from argus.core.schemas import CircuitBreakerAction, CircuitBreakerReason
from argus.core.tenancy import Role, TenantContext
from argus.governance.budget_guard import BudgetGuard
from argus.governance.loop_detector import LoopDetector
from argus.governance.mcp_proxy import McpGovernanceProxy


@pytest.mark.asyncio
async def test_mcp_proxy_filters_tools_list_by_rbac() -> None:
    detector = LoopDetector()
    guard = BudgetGuard(backend=InMemoryBudgetStore())
    proxy = McpGovernanceProxy(loop_detector=detector, budget_guard=guard)

    available_tools = [
        {"name": "fetch_weather", "description": "Get current weather"},
        {"name": "delete_database", "description": "Drop production database"},
    ]

    # VIEWER: gets zero tools
    viewer_ctx = TenantContext(
        tenant_id="acme", workspace_id="ws1", actor_id="v1", role=Role.VIEWER
    )
    assert proxy.filter_tools_list(viewer_ctx, available_tools) == []

    # INGESTOR: gets only non-destructive tools
    ingestor_ctx = TenantContext(
        tenant_id="acme", workspace_id="ws1", actor_id="i1", role=Role.INGESTOR
    )
    filtered = proxy.filter_tools_list(ingestor_ctx, available_tools)
    assert len(filtered) == 1
    assert filtered[0]["name"] == "fetch_weather"

    # OPERATOR: gets full tool set
    operator_ctx = TenantContext(
        tenant_id="acme", workspace_id="ws1", actor_id="op1", role=Role.OPERATOR
    )
    assert len(proxy.filter_tools_list(operator_ctx, available_tools)) == 2


@pytest.mark.asyncio
async def test_mcp_proxy_intercepts_destructive_tool_and_pauses_for_c2() -> None:
    detector = LoopDetector()
    guard = BudgetGuard(backend=InMemoryBudgetStore())
    proxy = McpGovernanceProxy(loop_detector=detector, budget_guard=guard)
    ctx = TenantContext(
        tenant_id="acme", workspace_id="ws1", actor_id="op1", role=Role.OPERATOR
    )
    session_id = new_uuid7()

    verdict, pending = await proxy.intercept_tool_call(
        ctx=ctx,
        session_id=session_id,
        tool_call_id="call_abc_123",
        tool_name="delete_account",
        tool_args={"user_id": "u999"},
        estimated_cost_usd=0.01,
        hard_cap_usd=5.0,
    )

    assert not verdict.tripped
    assert verdict.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2
    assert pending is not None
    assert pending.tool_name == "delete_account"
    assert pending.is_destructive is True
    # Verify cryptographic binding hash is present
    assert len(pending.request_digest_sha256) == 64


@pytest.mark.asyncio
async def test_mcp_proxy_trips_circuit_breaker_on_repetitive_loop() -> None:
    detector = LoopDetector(max_exact_repetitions=2)
    guard = BudgetGuard(backend=InMemoryBudgetStore())
    proxy = McpGovernanceProxy(loop_detector=detector, budget_guard=guard)
    ctx = TenantContext(
        tenant_id="acme", workspace_id="ws1", actor_id="op1", role=Role.OPERATOR
    )
    session_id = new_uuid7()

    # Step 1: Safe read tool
    v1, _ = await proxy.intercept_tool_call(
        ctx=ctx,
        session_id=session_id,
        tool_call_id="c1",
        tool_name="read_file",
        tool_args={"path": "logs.txt"},
    )
    assert v1.recommended_action == CircuitBreakerAction.ALLOW

    # Step 2: Identical read tool -> trips Tier 1 loop breaker
    v2, _ = await proxy.intercept_tool_call(
        ctx=ctx,
        session_id=session_id,
        tool_call_id="c2",
        tool_name="read_file",
        tool_args={"path": "logs.txt"},
    )
    assert v2.tripped is True
    assert v2.reason == CircuitBreakerReason.EXACT_TOOL_LOOP
    assert v2.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2
