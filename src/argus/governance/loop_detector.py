"""3-Tier automated circuit breaker engine for detecting repetitive reasoning cycles.

Tier 1: Exact Action/Payload Hash (O(1)) - SHA-256 canonical hash of tool/args or thoughts.
Tier 2: Sequence Oscillation & SimHash (O(W)) - Catches A -> B -> A -> B oscillatory cycles.
Tier 3: Semantic Stagnation (O(W * D)) - Deterministic local TF-IDF n-gram cosine similarity.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from argus.core.schemas import (
    CircuitBreakerAction,
    CircuitBreakerReason,
    CircuitBreakerVerdict,
    compute_canonical_sha256,
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
    text_content: str
    is_tool_call: bool
    term_vector: dict[str, float] = field(default_factory=dict)


class LoopDetector:
    """Multi-tier agent loop detection engine with zero external API dependencies ($0 spend)."""

    def __init__(
        self,
        *,
        window_size: int = 15,
        max_exact_repetitions: int = 3,
        max_oscillations: int = 2,
        semantic_threshold: float = 0.65,
        max_semantic_repetitions: int = 2,
    ) -> None:
        if window_size < 3:
            raise ValueError("window_size must be >= 3.")
        self.window_size = window_size
        self.max_exact_repetitions = max_exact_repetitions
        self.max_oscillations = max_oscillations
        self.semantic_threshold = semantic_threshold
        self.max_semantic_repetitions = max_semantic_repetitions

        # Session-keyed sliding history: session_id -> list[StepObservation]
        self._history: dict[str, list[StepObservation]] = defaultdict(list)

    def reset_session(self, session_id: str) -> None:
        """Clear memory buffer for a terminated or resumed session."""
        self._history.pop(session_id, None)

    def evaluate_step(
        self,
        *,
        session_id: str,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        thought_text: str = "",
        accumulated_cost_usd: float = 0.0,
        budget_limit_usd: float = 100.0,
    ) -> CircuitBreakerVerdict:
        """Evaluate an incoming agent step across all 3 tiers in increasing order of complexity."""
        is_tool = tool_name is not None
        if is_tool:
            norm_args = tool_args or {}
            canonical_payload = {"tool": tool_name, "args": norm_args}
            exact_hash = compute_canonical_sha256(canonical_payload)
            signature = f"TOOL:{tool_name}:{exact_hash[:8]}"
            rep_text = f"{tool_name} {canonical_payload}"
        else:
            exact_hash = compute_canonical_sha256(thought_text.strip())
            signature = f"THOUGHT:{exact_hash[:8]}"
            rep_text = thought_text.strip()

        term_vec = _build_l2_normalized_vector(rep_text)

        obs = StepObservation(
            exact_hash=exact_hash,
            signature=signature,
            text_content=rep_text,
            is_tool_call=is_tool,
            term_vector=term_vec,
        )

        history = self._history[session_id]

        # Tier 1: Exact Hash Repetition Check
        tier1_verdict = self._check_tier1(history, obs, accumulated_cost_usd, budget_limit_usd)
        if tier1_verdict.tripped:
            return tier1_verdict

        # Tier 2: Sequence Oscillation (A -> B -> A -> B)
        tier2_verdict = self._check_tier2(history, obs, accumulated_cost_usd, budget_limit_usd)
        if tier2_verdict.tripped:
            return tier2_verdict

        # Tier 3: Semantic Stagnation (Cosine similarity over non-exact steps / thoughts)
        tier3_verdict = self._check_tier3(history, obs, accumulated_cost_usd, budget_limit_usd)
        if tier3_verdict.tripped:
            return tier3_verdict

        # Step is clean: record to history and allow
        history.append(obs)
        if len(history) > self.window_size:
            history.pop(0)

        return CircuitBreakerVerdict(
            tripped=False,
            reason=CircuitBreakerReason.NONE,
            similarity_score=0.0,
            repeated_count=0,
            accumulated_cost_usd=accumulated_cost_usd,
            budget_limit_usd=budget_limit_usd,
            recommended_action=CircuitBreakerAction.ALLOW,
            diagnostic_message="Step clear of repetitive reasoning cycles.",
        )

    def _check_tier1(
        self,
        history: list[StepObservation],
        current: StepObservation,
        accumulated_cost_usd: float,
        budget_limit_usd: float,
    ) -> CircuitBreakerVerdict:
        """Check for identical consecutive action/tool repetitions."""
        if not history:
            return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

        consecutive = 0
        for past in reversed(history):
            if past.exact_hash == current.exact_hash:
                consecutive += 1
            else:
                break

        total_consecutive = consecutive + 1
        if total_consecutive >= self.max_exact_repetitions:
            return CircuitBreakerVerdict(
                tripped=True,
                reason=CircuitBreakerReason.EXACT_TOOL_LOOP,
                similarity_score=1.0,
                repeated_count=total_consecutive,
                accumulated_cost_usd=accumulated_cost_usd,
                budget_limit_usd=budget_limit_usd,
                recommended_action=CircuitBreakerAction.PAUSE_FOR_C2,
                diagnostic_message=(
                    f"Tier 1: Identical action '{current.signature}' repeated "
                    f"{total_consecutive} times consecutively."
                ),
            )

        return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

    def _check_tier2(
        self,
        history: list[StepObservation],
        current: StepObservation,
        accumulated_cost_usd: float,
        budget_limit_usd: float,
    ) -> CircuitBreakerVerdict:
        """Check for cycle patterns such as A -> B -> A -> B or A -> B -> C -> A -> B -> C."""
        if len(history) < 3:
            return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

        seq = [h.signature for h in history] + [current.signature]

        for k in (2, 3):
            if len(seq) >= k * self.max_oscillations:
                is_oscillating = True
                target_block = seq[-k:]
                for cycle in range(1, self.max_oscillations):
                    start = -(cycle + 1) * k
                    end = -cycle * k
                    block = seq[start:end]
                    if block != target_block:
                        is_oscillating = False
                        break

                if is_oscillating:
                    cycle_repr = " -> ".join(target_block)
                    return CircuitBreakerVerdict(
                        tripped=True,
                        reason=CircuitBreakerReason.STATE_OSCILLATION,
                        similarity_score=0.95,
                        repeated_count=self.max_oscillations,
                        accumulated_cost_usd=accumulated_cost_usd,
                        budget_limit_usd=budget_limit_usd,
                        recommended_action=CircuitBreakerAction.PAUSE_FOR_C2,
                        diagnostic_message=(
                            f"Tier 2: Detected oscillatory loop ({cycle_repr}) repeated "
                            f"{self.max_oscillations} times."
                        ),
                    )

        return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

    def _check_tier3(
        self,
        history: list[StepObservation],
        current: StepObservation,
        accumulated_cost_usd: float,
        budget_limit_usd: float,
    ) -> CircuitBreakerVerdict:
        """Check semantic similarity across reasoning thoughts to detect paraphrased stagnation.

        Tier 3 specifically targets non-tool reasoning loops (thought stagnation) or distinct tools
        with repetitive semantic goals, while leaving distinct discrete tools to Tier 1 and Tier 2.
        """
        # If current step is a tool call, we only compare against previous steps
        # if they are thoughts or if thought_text was provided.
        if current.is_tool_call:
            return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

        if not history or not current.term_vector:
            return self._clean_verdict(accumulated_cost_usd, budget_limit_usd)

        similar_count = 0
        max_sim = 0.0

        for past in reversed(history[-self.window_size :]):
            # Only compare thoughts against thoughts for semantic stagnation
            if past.is_tool_call:
                continue
            sim = _cosine_similarity(current.term_vector, past.term_vector)
            if sim > max_sim:
                max_sim = sim
            if sim >= self.semantic_threshold:
                similar_count += 1

        if similar_count >= self.max_semantic_repetitions:
            return CircuitBreakerVerdict(
                tripped=True,
                reason=CircuitBreakerReason.SEMANTIC_STAGNATION,
                similarity_score=round(max_sim, 4),
                repeated_count=similar_count + 1,
                accumulated_cost_usd=accumulated_cost_usd,
                budget_limit_usd=budget_limit_usd,
                recommended_action=CircuitBreakerAction.NUDGE_BACKTRACK,
                diagnostic_message=(
                    f"Tier 3: Semantic stagnation detected with similarity {max_sim:.3f} >= "
                    f"{self.semantic_threshold} across {similar_count + 1} steps."
                ),
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
            recommended_action=CircuitBreakerAction.ALLOW,
            diagnostic_message="",
        )
