"""Model Context Protocol (MCP) JSON-RPC 2.0 Governance Proxy & Interceptor.

Provides protocol-level interception for MCP client-server communication:
- Intercepts tools/list to enforce Attribute-Based Access Control (ABAC) and
  sanitizes third-party tool descriptions against prompt-injection jailbreak attacks.
- Intercepts tools/call to enforce pre-execution circuit breaking, budget validation,
  shell-injection and prompt-injection threat scanning, and Human-in-the-Loop approval workflows.
- Native JSON-RPC 2.0 transparent protocol mediation gateway.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from argus.core.schemas import (
    CircuitBreakerAction,
    CircuitBreakerReason,
    CircuitBreakerVerdict,
    PendingToolCall,
)
from argus.core.tenancy import Role, TenantContext
from argus.governance.budget_guard import BudgetGuard
from argus.governance.loop_detector import LoopDetector
from argus.governance.security_scanner import (
    sanitize_tool_description,
    scan_tool_arguments,
)

# Known destructive tool name patterns requiring human operator confirmation
_DEFAULT_DESTRUCTIVE_PATTERNS: tuple[str, ...] = (
    "delete",
    "drop",
    "remove",
    "terminate",
    "truncate",
    "kill",
    "destroy",
    "format",
    "wipe",
    "execute_shell",
    "exec",
    "transfer",
    "write_file",
    "send_payment",
    "chmod",
    "chown",
)


class McpGovernanceProxy:
    """Enterprise MCP JSON-RPC 2.0 proxy enforcing security and circuit breakers on tools."""

    def __init__(
        self,
        *,
        loop_detector: LoopDetector,
        budget_guard: BudgetGuard,
        destructive_tools: set[str] | None = None,
        extra_destructive_patterns: Sequence[str] = (),
        enforce_injection_scan: bool = True,
    ) -> None:
        self._loop_detector = loop_detector
        self._budget_guard = budget_guard
        self._destructive_tools = {t.lower() for t in (destructive_tools or set())}
        self._destructive_patterns = _DEFAULT_DESTRUCTIVE_PATTERNS + tuple(
            p.lower() for p in extra_destructive_patterns if p
        )
        self._enforce_injection_scan = enforce_injection_scan

    def is_destructive_tool(self, tool_name: str) -> bool:
        """Determine if a tool call requires explicit human C2 approval before execution."""
        lowered = tool_name.lower()
        if lowered in self._destructive_tools:
            return True
        return any(pattern in lowered for pattern in self._destructive_patterns)

    def filter_tools_list(
        self,
        ctx: TenantContext,
        available_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Filter and sanitize tools/list based on RBAC and prompt-injection defense."""
        # Viewers have zero tool execution capability: return empty list
        if ctx.role == Role.VIEWER:
            return []

        # Ingestors are read-only telemetry emitters: omit destructive tools
        if ctx.role == Role.INGESTOR:
            candidates = [
                t
                for t in available_tools
                if not self.is_destructive_tool(str(t.get("name", "")))
            ]
        else:
            candidates = list(available_tools)

        # Sanitize tool descriptions against prompt-injection jailbreaks
        sanitized_tools: list[dict[str, Any]] = []
        for t in candidates:
            tool_copy = dict(t)
            if self._enforce_injection_scan and "description" in tool_copy:
                raw_desc = str(tool_copy["description"])
                tool_copy["description"] = sanitize_tool_description(raw_desc)
            sanitized_tools.append(tool_copy)

        return sanitized_tools

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
        """Intercept and evaluate an MCP tools/call request before execution."""
        # Step 0: Pre-execution Threat Scanning (Shell & Prompt Injection)
        if self._enforce_injection_scan:
            has_threat, threat_msg = scan_tool_arguments(tool_args)
            if has_threat and threat_msg:
                pending = PendingToolCall(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    is_destructive=True,
                    security_risk=threat_msg,
                )
                security_verdict = CircuitBreakerVerdict(
                    tripped=True,
                    trip_tier=None,
                    reason=CircuitBreakerReason.SECURITY_VIOLATION,
                    similarity_score=1.0,
                    repeated_count=1,
                    accumulated_cost_usd=0.0,
                    budget_limit_usd=hard_cap_usd,
                    wasted_cost_usd=0.0,
                    recommended_action=CircuitBreakerAction.PAUSE_FOR_C2,
                    diagnostic_message=(
                        f"Security violation in '{tool_name}' arguments: {threat_msg}"
                    ),
                )
                return security_verdict, pending

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
                security_risk=None,
            )
            pause_verdict = CircuitBreakerVerdict(
                tripped=False,
                reason=CircuitBreakerReason.HIGH_RISK_TOOL,
                similarity_score=loop_verdict.similarity_score,
                repeated_count=loop_verdict.repeated_count,
                accumulated_cost_usd=current_spend,
                budget_limit_usd=hard_cap_usd,
                wasted_cost_usd=0.0,
                recommended_action=CircuitBreakerAction.PAUSE_FOR_C2,
                diagnostic_message=(
                    f"Tool '{tool_name}' classified as destructive/high-risk; "
                    "execution paused awaiting operator approval."
                ),
            )
            return pause_verdict, pending

        # All checks passed: Allow execution
        return budget_verdict, None

    async def handle_jsonrpc(
        self,
        *,
        ctx: TenantContext,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any], PendingToolCall | None]:
        """Handle transparent JSON-RPC 2.0 MCP requests."""
        req_id = request.get("id")
        method = str(request.get("method", ""))
        params = request.get("params", {}) or {}

        if method == "tools/list":
            tools = params.get("tools", [])
            filtered = self.filter_tools_list(ctx, tools)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": filtered},
            }, None

        if method == "tools/call":
            session_raw = params.get("session_id")
            session_id = uuid.UUID(str(session_raw)) if session_raw else uuid.uuid4()
            tool_name = str(params.get("name", ""))
            tool_args = params.get("arguments", {}) or {}
            tool_call_id = str(params.get("tool_call_id") or req_id or uuid.uuid4())
            cost = float(params.get("estimated_cost_usd", 0.001))
            cap = float(params.get("hard_cap_usd", 100.0))

            verdict, pending = await self.intercept_tool_call(
                ctx=ctx,
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args=tool_args,
                estimated_cost_usd=cost,
                hard_cap_usd=cap,
            )

            if verdict.tripped:
                error_code = (
                    -32003
                    if verdict.reason == CircuitBreakerReason.SECURITY_VIOLATION
                    else -32002
                    if verdict.reason == CircuitBreakerReason.BUDGET_EXCEEDED
                    else -32000
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": error_code,
                        "message": verdict.diagnostic_message,
                        "data": {
                            "reason": verdict.reason.value,
                            "recommended_action": verdict.recommended_action.value,
                        },
                    },
                }, pending

            if verdict.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2 and pending:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32001,
                        "message": verdict.diagnostic_message,
                        "data": {
                            "status": "PAUSED_C2",
                            "tool_call_id": pending.tool_call_id,
                            "request_digest_sha256": pending.request_digest_sha256,
                        },
                    },
                }, pending

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "status": "ALLOWED",
                    "tool_name": tool_name,
                },
            }, None

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: '{method}'",
            },
        }, None


__all__ = [
    "McpGovernanceProxy",
]
