"""3-Tier automated circuit breaker engine for detecting repetitive reasoning cycles.

Tier 1: Exact Action/Payload Hash (O(1)) - SHA-256 canonical hash of tool/args or thoughts.
Tier 2: Sequence Oscillation & 64-bit SimHash (O(W)) - Catches A -> B -> A -> B oscillatory cycles
        and near-duplicate tool argument loops with volatile fields (timestamps, IDs).
Tier 3: Semantic Stagnation (O(W * D)) - Deterministic local TF-IDF n-gram cosine similarity
        with automated escalation from NUDGE_BACKTRACK to PAUSE_FOR_C2.
"""

from __future__ import annotations

import math
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any

from argus.core.schemas import (
    CircuitBreakerAction,
    CircuitBreakerReason,
    CircuitBreakerVerdict,
    compute_canonical_sha256,
)
from argus.governance.simhash import (
    hamming_distance64,
    payload_simhash,
)

_TOKEN_RE = re.compile(r"(?u)\b\w+\b")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "he",
        "in",
        "is",
        "it",
        "its",
        "let",
        "me",
        "my",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
    }
)

DEFAULT_NUDGE_TEMPLATE = (
    "[ARGUS CIRCUIT BREAKER] Reasoning stagnation detected (similarity: {similarity:.2f}). "
    "You have repeated similar thoughts across {count} steps without task progress. "
    "Do NOT repeat previous hypotheses. Re-evaluate your assumptions, change your approach, "
    "switch to an alternative tool, or summarize current findings and halt."
)


def _build_l2_normalized_vector(text: str) -> dict[str, float]:
    """Tokenize and return an L2-normalized sparse term vector using words and 3-grams."""
    all_words = _TOKEN_RE.findall(text.lower())
    if not all_words:
        return {}

    content_words = [w for w in all_words if w not in _STOPWORDS]
    base_words = content_words if content_words else all_words
    tokens: list[str] = list(base_words)

    # Substring character 3-grams to catch inflectional variants (e.g. subscription/subscriptions)
    for w in base_words:
        if len(w) >= 3:
            for j in range(len(w) - 2):
                tokens.append(w[j : j + 3])

    counts = Counter(tokens)
    norm = math.sqrt(sum(c * c for c in counts.values()))
    if norm == 0.0:
        return {}
    return {k: v / norm for k, v in counts.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Compute cosine similarity between two L2-normalized sparse vectors."""
    if not vec_a or not vec_b:
        return 0.0
    common = set(vec_a.keys()) & set(vec_b.keys())
    if not common:
        return 0.0
    return min(1.0, max(0.0, sum(vec_a[t] * vec_b[t] for t in common)))


@dataclass(frozen=True)
class StepObservation:
    """Immutable record of an agent step for sliding-window cycle analysis."""

    exact_hash: str
    signature: str
    tool_name: str | None
    simhash: int
    text_content: str
    is_tool_call: bool
    cost_usd: float = 0.0
    term_vector: dict[str, float] = field(default_factory=dict)


class LoopDetector:
    """Enterprise multi-tier loop detection engine ($0 spend)."""

    def __init__(
        self,
        *,
        window_size: int = 15,
        max_exact_repetitions: int = 3,
        max_oscillations: int = 2,
        semantic_threshold: float = 0.65,
        max_semantic_repetitions: int = 2,
        simhash_max_hamming: int = 3,
        max_tracked_sessions: int = 10000,
    ) -> None:
        if window_size < 3:
            raise ValueError("window_size must be >= 3.")
        self.window_size = window_size
        self.max_exact_repetitions = max_exact_repetitions
        self.max_oscillations = max_oscillations
        self.semantic_threshold = semantic_threshold
        self.max_semantic_repetitions = max_semantic_repetitions
        self.simhash_max_hamming = simhash_max_hamming
        self.max_tracked_sessions = max_tracked_sessions

        # Tenant-isolated sliding history: key -> list[StepObservation]
        self._history: OrderedDict[str, list[StepObservation]] = OrderedDict()
        # Track whether a session has received a Tier 3 nudge to allow escalation: key -> int count
        self._nudged_sessions: OrderedDict[str, int] = OrderedDict()

    def _get_key(self, session_id: str, tenant_id: str | None = None) -> str:
        return f"{tenant_id}:{session_id}" if tenant_id else session_id

    def reset_session(self, session_id: str, tenant_id: str | None = None) -> None:
        """Clear memory buffer for a terminated or resumed session."""
        if tenant_id:
            key = self._get_key(session_id, tenant_id)
            self._history.pop(key, None)
            self._nudged_sessions.pop(key, None)
        else:
            # Fallback: remove all matching keys across any tenant
            target_suffix = f":{session_id}"
            keys_to_remove = [
                k for k in self._history if k == session_id or k.endswith(target_suffix)
            ]
            for k in keys_to_remove:
                self._history.pop(k, None)
                self._nudged_sessions.pop(k, None)

    def evaluate_step(
        self,
        *,
        session_id: str,
        tenant_id: str | None = None,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        thought_text: str = "",
        step_cost_usd: float = 0.0,
        accumulated_cost_usd: float = 0.0,
        budget_limit_usd: float = 100.0,
    ) -> CircuitBreakerVerdict:
        """Evaluate an incoming agent step across all 3 tiers in increasing order of complexity."""
        is_tool = tool_name is not None
        if is_tool:
            norm_args = tool_args or {}
            canonical_payload = {"tool": tool_name, "args": norm_args}
            exact_hash = compute_canonical_sha256(canonical_payload)
            simhash = payload_simhash(canonical_payload)
            signature = f"TOOL:{tool_name}:{exact_hash[:8]}"
            rep_text = f"{tool_name} {canonical_payload}"
        else:
            exact_hash = compute_canonical_sha256(thought_text.strip())
            simhash = payload_simhash(thought_text.strip())
            signature = f"THOUGHT:{exact_hash[:8]}"
            rep_text = thought_text.strip()

        term_vec = _build_l2_normalized_vector(rep_text)

        obs = StepObservation(
            exact_hash=exact_hash,
            signature=signature,
            tool_name=tool_name,
            simhash=simhash,
            text_content=rep_text,
            is_tool_call=is_tool,
            cost_usd=step_cost_usd,
            term_vector=term_vec,
        )

        key = self._get_key(session_id, tenant_id)

        # LRU maintenance for bounded session tracking
        if key in self._history:
            self._history.move_to_end(key)
            history = self._history[key]
        else:
            if len(self._history) >= self.max_tracked_sessions:
                self._history.popitem(last=False)
            history = []
            self._history[key] = history

        # Tier 1: Exact Hash Repetition Check
        tier1_verdict = self._check_tier1(
            history, obs, step_cost_usd, accumulated_cost_usd, budget_limit_usd
        )
        if tier1_verdict.tripped:
            return tier1_verdict

        # Tier 2: Sequence Oscillation & SimHash Check (A -> B -> A -> B)
        tier2_verdict = self._check_tier2(
            history, obs, step_cost_usd, accumulated_cost_usd, budget_limit_usd
        )
        if tier2_verdict.tripped:
            return tier2_verdict

        # Tier 3: Semantic Stagnation & Escalation Check
        tier3_verdict = self._check_tier3(
            key, history, obs, step_cost_usd, accumulated_cost_usd, budget_limit_usd
        )
        if tier3_verdict.tripped:
            if tier3_verdict.recommended_action == CircuitBreakerAction.NUDGE_BACKTRACK:
                history.append(obs)
                if len(history) > self.window_size:
                    history.pop(0)
            return tier3_verdict

        # Step is clean: clear any active nudge and append observation
        self._nudged_sessions.pop(key, None)
        history.append(obs)
        if len(history) > self.window_size:
            history.pop(0)

        return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

    def _check_tier1(
        self,
        history: list[StepObservation],
        current: StepObservation,
        step_cost_usd: float,
        accumulated_cost_usd: float,
        budget_limit_usd: float,
    ) -> CircuitBreakerVerdict:
        """Check for identical consecutive action/tool repetitions."""
        if not history:
            return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

        consecutive = 0
        wasted_cost = step_cost_usd
        for past in reversed(history):
            if past.exact_hash == current.exact_hash:
                consecutive += 1
                wasted_cost += past.cost_usd
            else:
                break

        total_consecutive = consecutive + 1
        if total_consecutive >= self.max_exact_repetitions:
            return CircuitBreakerVerdict(
                tripped=True,
                trip_tier=1,
                reason=CircuitBreakerReason.EXACT_TOOL_LOOP,
                similarity_score=1.0,
                hamming_distance=0,
                repeated_count=total_consecutive,
                accumulated_cost_usd=accumulated_cost_usd,
                budget_limit_usd=budget_limit_usd,
                wasted_cost_usd=round(wasted_cost, 6),
                recommended_action=CircuitBreakerAction.PAUSE_FOR_C2,
                diagnostic_message=(
                    f"Tier 1: Identical action '{current.signature}' repeated "
                    f"{total_consecutive} times consecutively."
                ),
            )

        return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

    def _steps_match(self, a: StepObservation, b: StepObservation) -> tuple[bool, int]:
        """Determine if two steps are identical or near-duplicates under SimHash."""
        if a.exact_hash == b.exact_hash:
            return True, 0
        if a.is_tool_call and b.is_tool_call and a.tool_name == b.tool_name and a.tool_name:
            dist = hamming_distance64(a.simhash, b.simhash)
            if dist <= self.simhash_max_hamming:
                return True, dist
        return False, 64

    def _check_tier2(
        self,
        history: list[StepObservation],
        current: StepObservation,
        step_cost_usd: float,
        accumulated_cost_usd: float,
        budget_limit_usd: float,
    ) -> CircuitBreakerVerdict:
        """Check for cycle patterns such as A -> B -> A -> B or A -> B -> C -> A -> B -> C.

        Uses structural position matching and 64-bit SimHash Hamming distance to catch
        cycles even when arguments include volatile timestamps, sequence IDs, or whitespace.
        """
        if len(history) < 3:
            return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

        full_seq = [*history, current]

        for k in (2, 3):
            needed_len = k * self.max_oscillations
            if len(full_seq) >= needed_len:
                is_oscillating = True
                target_block = full_seq[-k:]
                min_hamming = 64
                total_cycle_cost = step_cost_usd

                for cycle in range(1, self.max_oscillations):
                    start = -(cycle + 1) * k
                    end = -cycle * k
                    block = full_seq[start:end]

                    for step_idx in range(k):
                        matches, dist = self._steps_match(target_block[step_idx], block[step_idx])
                        if not matches:
                            is_oscillating = False
                            break
                        min_hamming = min(min_hamming, dist)
                        total_cycle_cost += block[step_idx].cost_usd

                    if not is_oscillating:
                        break

                if is_oscillating:
                    # Also include earlier steps in target_block (excluding current already counted)
                    for step_obs in target_block[:-1]:
                        total_cycle_cost += step_obs.cost_usd

                    cycle_names = [s.tool_name or s.signature for s in target_block]
                    cycle_repr = " -> ".join(cycle_names)
                    sim = round(1.0 - (min_hamming / 64.0), 4)

                    return CircuitBreakerVerdict(
                        tripped=True,
                        trip_tier=2,
                        reason=CircuitBreakerReason.STATE_OSCILLATION,
                        similarity_score=sim,
                        hamming_distance=min_hamming,
                        repeated_count=self.max_oscillations,
                        accumulated_cost_usd=accumulated_cost_usd,
                        budget_limit_usd=budget_limit_usd,
                        wasted_cost_usd=round(total_cycle_cost, 6),
                        recommended_action=CircuitBreakerAction.PAUSE_FOR_C2,
                        diagnostic_message=(
                            f"Tier 2: Detected oscillatory cycle ({cycle_repr}) repeated "
                            f"{self.max_oscillations} times (SimHash min Hamming dist: "
                            f"{min_hamming})."
                        ),
                    )

        return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

    def _check_tier3(
        self,
        key: str,
        history: list[StepObservation],
        current: StepObservation,
        step_cost_usd: float,
        accumulated_cost_usd: float,
        budget_limit_usd: float,
    ) -> CircuitBreakerVerdict:
        """Check semantic similarity across reasoning thoughts with automated escalation."""
        # Non-tool reasoning thoughts only
        if current.is_tool_call:
            return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

        if not history or not current.term_vector:
            return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

        similar_count = 0
        max_sim = 0.0
        wasted_cost = step_cost_usd

        for past in reversed(history[-self.window_size :]):
            if past.is_tool_call:
                continue
            sim = _cosine_similarity(current.term_vector, past.term_vector)
            if sim > max_sim:
                max_sim = sim
            if sim >= self.semantic_threshold:
                similar_count += 1
                wasted_cost += past.cost_usd

        if similar_count >= self.max_semantic_repetitions:
            nudged_count = self._nudged_sessions.get(key, 0)

            if nudged_count == 0:
                # First trip: issue NUDGE_BACKTRACK with structured injection instruction
                self._nudged_sessions[key] = 1
                nudge_instruction = DEFAULT_NUDGE_TEMPLATE.format(
                    similarity=max_sim,
                    count=similar_count + 1,
                )
                return CircuitBreakerVerdict(
                    tripped=True,
                    trip_tier=3,
                    reason=CircuitBreakerReason.SEMANTIC_STAGNATION,
                    similarity_score=round(max_sim, 4),
                    repeated_count=similar_count + 1,
                    accumulated_cost_usd=accumulated_cost_usd,
                    budget_limit_usd=budget_limit_usd,
                    wasted_cost_usd=round(wasted_cost, 6),
                    recommended_action=CircuitBreakerAction.NUDGE_BACKTRACK,
                    diagnostic_message=(
                        f"Tier 3: Semantic stagnation detected with similarity {max_sim:.3f} >= "
                        f"{self.semantic_threshold} across {similar_count + 1} steps."
                    ),
                    nudge_instruction=nudge_instruction,
                )

            # Second consecutive trip after previous nudge: Escalate to PAUSE_FOR_C2
            self._nudged_sessions[key] = nudged_count + 1
            return CircuitBreakerVerdict(
                tripped=True,
                trip_tier=3,
                reason=CircuitBreakerReason.SEMANTIC_STAGNATION,
                similarity_score=round(max_sim, 4),
                repeated_count=similar_count + 1,
                accumulated_cost_usd=accumulated_cost_usd,
                budget_limit_usd=budget_limit_usd,
                wasted_cost_usd=round(wasted_cost, 6),
                recommended_action=CircuitBreakerAction.PAUSE_FOR_C2,
                diagnostic_message=(
                    f"Tier 3: Consecutive semantic stagnation after backtrack nudge "
                    f"({max_sim:.3f} >= {self.semantic_threshold}). "
                    "Pausing session for operator C2 review."
                ),
                nudge_instruction=None,
            )

        return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

    def _clean_verdict(
        self,
        accumulated_cost_usd: float,
        budget_limit_usd: float,
    ) -> CircuitBreakerVerdict:
        return CircuitBreakerVerdict(
            tripped=False,
            reason=CircuitBreakerReason.NONE,
            similarity_score=0.0,
            repeated_count=0,
            accumulated_cost_usd=accumulated_cost_usd,
            budget_limit_usd=budget_limit_usd,
            wasted_cost_usd=0.0,
            recommended_action=CircuitBreakerAction.ALLOW,
            diagnostic_message="",
        )


__all__ = [
    "DEFAULT_NUDGE_TEMPLATE",
    "LoopDetector",
    "StepObservation",
]
