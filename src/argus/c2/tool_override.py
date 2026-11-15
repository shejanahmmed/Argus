"""Mid-execution tool call override engine.

Allows operators to approve, modify arguments, reject, or mock tool responses
for intercepted tool calls bound cryptographically by request_digest_sha256.
"""

from __future__ import annotations

from typing import Any

from argus.core.schemas import C2OverrideCommand, PendingToolCall
from argus.core.tenancy import TenantContext
from argus.governance.security_scanner import scan_tool_arguments


class ToolOverrideEngine:
    """Processes operator decisions for intercepted tool calls in PAUSED_C2."""

    def process_override(
        self,
        ctx: TenantContext,
        command: C2OverrideCommand,
        pending_call: PendingToolCall,
    ) -> tuple[dict[str, Any], bool, str]:
        """Execute operator override decision on an intercepted tool call.

        Returns:
            result_payload: Effective arguments or mock result.
            should_execute: True if tool should run with payload; False if mocked or rejected.
            status_message: Human-readable diagnostic description of the intervention.
        """
        ctx.assert_can_mutate_c2()

        spec = command.tool_override
        if spec is None:
            raise ValueError("C2OverrideCommand lacks tool_override specification.")

        # Cryptographically verify that the operator decision binds to the exact intercepted request
        if spec.request_digest_sha256 != pending_call.request_digest_sha256:
            raise ValueError(
                f"Digest mismatch on tool override: command digest '{spec.request_digest_sha256}' "
                f"does not match pending tool call digest '{pending_call.request_digest_sha256}'."
            )

        if spec.decision == "approve":
            return (
                pending_call.tool_args,
                True,
                f"Tool '{pending_call.tool_name}' approved by operator '{command.operator_id}'.",
            )

        if spec.decision == "edit":
            edited_args = spec.modified_args or {}
            tripped, threat = scan_tool_arguments(edited_args)
            if tripped:
                raise ValueError(
                    f"Security threat detected in operator modified arguments: {threat}"
                )
            return (
                edited_args,
                True,
                (
                    f"Tool '{pending_call.tool_name}' arguments modified by "
                    f"operator '{command.operator_id}'."
                ),
            )

        if spec.decision == "mock":
            mock_res = spec.mock_output or {}
            return (
                mock_res,
                False,
                f"Tool '{pending_call.tool_name}' execution bypassed; operator injected mock.",
            )

        if spec.decision == "reject":
            reason = spec.rejection_reason or "Rejected by operator."
            return (
                {
                    "error": "TOOL_EXECUTION_REJECTED_BY_OPERATOR",
                    "tool_call_id": pending_call.tool_call_id,
                    "reason": reason,
                },
                False,
                f"Tool '{pending_call.tool_name}' rejected by operator: {reason}",
            )

        raise ValueError(f"Unknown tool override decision: '{spec.decision}'.")
