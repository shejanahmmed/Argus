"""One-click state mutation presets catalog for Command & Control (C2) interventions."""

from __future__ import annotations

from argus.core.schemas import JsonPatchOp, StatePreset

_BUILTIN_PRESETS: tuple[StatePreset, ...] = (
    StatePreset(
        preset_id="safe-fallback-plan",
        name="Safe Fallback Plan",
        description=(
            "Replaces the active execution plan with a safe, read-only diagnostic "
            "audit to halt destructive actions and identify system state."
        ),
        patches=(
            JsonPatchOp(
                op="replace",
                path="/plan/0",
                value="Execute read-only schema and ledger audit",
            ),
        ),
        recommended_for=("TRIPPED_LOOP", "HIGH_RISK_TOOL"),
    ),
    StatePreset(
        preset_id="force-sandbox-replica",
        name="Force Sandbox Replica",
        description=(
            "Redirects downstream database connections, cloud infrastructure, "
            "and write targets to an isolated ephemeral sandbox replica."
        ),
        patches=(
            JsonPatchOp(op="add", path="/target_env", value="isolated_sandbox_replica"),
            JsonPatchOp(op="add", path="/read_only", value=True),
        ),
        target_env_override="isolated_sandbox_replica",
        recommended_for=("HIGH_RISK_TOOL", "SECURITY_VIOLATION"),
    ),
    StatePreset(
        preset_id="clear-loop-state",
        name="Clear Loop State",
        description=(
            "Clears internal loop flags, resets iteration counters, and acknowledges "
            "human operator guidance to unblock reasoning cycles."
        ),
        patches=(
            JsonPatchOp(op="add", path="/operator_cleared_loop", value=True),
            JsonPatchOp(op="add", path="/retry_count", value=0),
            JsonPatchOp(op="add", path="/stagnation_detected", value=False),
        ),
        recommended_for=("TRIPPED_LOOP",),
    ),
    StatePreset(
        preset_id="budget-throttle-mode",
        name="Budget Throttle Mode",
        description=(
            "Forces agent runtime into lightweight token consumption mode, "
            "capping max tokens per step to 256 and restricting expensive tools."
        ),
        patches=(
            JsonPatchOp(op="add", path="/model_tier", value="lightweight"),
            JsonPatchOp(op="add", path="/max_tokens_per_step", value=256),
            JsonPatchOp(op="add", path="/allow_expensive_tools", value=False),
        ),
        recommended_for=("TRIPPED_BUDGET",),
    ),
)


def get_all_presets() -> list[StatePreset]:
    """Return all registered Command & Control state mutation presets."""
    return list(_BUILTIN_PRESETS)


def get_preset(preset_id: str) -> StatePreset | None:
    """Find a state mutation preset by unique preset ID."""
    for p in _BUILTIN_PRESETS:
        if p.preset_id == preset_id:
            return p
    return None


__all__ = [
    "get_all_presets",
    "get_preset",
]
