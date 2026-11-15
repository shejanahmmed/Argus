"""Model Context Protocol (MCP) JSON-RPC 2.0 Governance Proxy & Interceptor.

Provides protocol-level interception for MCP client-server communication:
- Intercepts tools/list to enforce Attribute-Based Access Control (ABAC).
- Intercepts tools/call to enforce pre-execution circuit breaking, budget validation,
  and Human-in-the-Loop approval workflows with cryptographic argument binding.
"""

from __future__ import annotations

import uuid
from typing import Any

from argus.core.schemas import (
    CircuitBreakerAction,
    CircuitBreakerVerdict,
    PendingToolCall,
)
from argus.core.tenancy import Role, TenantContext
from argus.governance.budget_guard import BudgetGuard
from argus.governance.loop_detector import LoopDetector

# Known destructive tool name patterns requiring human operator confirmation
_DESTRUCTIVE_NAME_PATTERNS: tuple[str, ...] = (
    "delete",
    "drop",
    "remove",
    "terminate",
    "execute_shell",
    "transfer",
    "write_file",
    "send_payment",
)


class McpGovernanceProxy:
    """Enterprise MCP JSON-RPC 2.0 proxy enforcing security and circuit breakers on tools."""

    def __init__(
        self,
        *,
        loop_detector: LoopDetector,
        budget_guard: BudgetGuard,
        destructive_tools: set[str] | None = None,
    ) -> None:
        self._loop_detector = loop_detector
        self._budget_guard = budget_guard
        self._destructive_tools = {t.lower() for t in (destructive_tools or set())}

    def is_destructive_tool(self, tool_name: str) -> bool:
        """Determine if a tool call requires explicit human C2 approval before execution."""
        lowered = tool_name.lower()
        if lowered in self._destructive_tools:
            return True
        return any(pattern in lowered for pattern in _DESTRUCTIVE_NAME_PATTERNS)

    def filter_tools_list(
        self,
        ctx: TenantContext,
        available_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Filter tools/list response based on the tenant actor's RBAC role (ABAC gate)."""
        # Viewers have zero tool execution capability: return empty list
        if ctx.role == Role.VIEWER:
            return []

        # Ingestors are read-only telemetry emitters: omit destructive tools
        if ctx.role == Role.INGESTOR:
            return [
                t
                for t in available_tools
                if not self.is_destructive_tool(str(t.get("name", "")))
            ]

        # Operators and Admins retain full tool exposure subject to runtime C2 approval
        return list(available_tools)

    async def intercept_tool_call(
        self,
        *,
        ctx: TenantContext,
        session_id: uuid.UUID,
        tool_call_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        estimated_cost_usd: float = 0.001,
        hard_cap_usd: float = 100.0,
    ) -> tuple[CircuitBreakerVerdict, PendingToolCall | None]:
        """Intercept and evaluate an MCP tools/call request before it hits backend systems.

        Returns:
            verdict: CircuitBreakerVerdict (ALLOW, PAUSE_FOR_C2, TERMINATE, etc.)
            pending_call: PendingToolCall record if human approval is required, else None.
        """
        # Step 1: Pre-execution Budget Check
        budget_verdict = await self._budget_guard.evaluate_and_reserve(
            ctx=ctx,
            session_id=session_id,
            requested_usd=estimated_cost_usd,
            hard_cap_usd=hard_cap_usd,
        )
        if budget_verdict.tripped:
            return budget_verdict, None

        current_spend = budget_verdict.accumulated_cost_usd

        # Step 2: 3-Tier Loop Detection Check
        loop_verdict = self._loop_detector.evaluate_step(
            session_id=str(session_id),
            tenant_id=ctx.tenant_id,
            tool_name=tool_name,
            tool_args=tool_args,
            step_cost_usd=estimated_cost_usd,
            accumulated_cost_usd=current_spend,
            budget_limit_usd=hard_cap_usd,
        )
        if loop_verdict.tripped:
            return loop_verdict, None

        # Step 3: Destructive Action & Human-in-the-Loop Policy Gate
        is_destructive = self.is_destructive_tool(tool_name)
        if is_destructive:
            pending = PendingToolCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args=tool_args,
                is_destructive=True,
            )
            pause_verdict = CircuitBreakerVerdict(
                tripped=False,
                reason=loop_verdict.reason,
                similarity_score=loop_verdict.similarity_score,
                repeated_count=loop_verdict.repeated_count,
                accumulated_cost_usd=current_spend,
                budget_limit_usd=hard_cap_usd,
                recommended_action=CircuitBreakerAction.PAUSE_FOR_C2,
                diagnostic_message=(
                    f"Tool '{tool_name}' classified as destructive/high-risk; "
                    "execution paused awaiting operator approval."
                ),
            )
            return pause_verdict, pending

        # All checks passed: Allow execution
        return budget_verdict, None
