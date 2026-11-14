"""Zero-spend deterministic agent trajectory evaluation metrics."""

from __future__ import annotations

from collections.abc import Sequence

from argus.core.schemas import ArgusSpan, SpanKind


class TrajectoryEvaluator:
    """Evaluates agent execution trajectories without requiring external paid LLM APIs."""

    def evaluate_tool_correctness(
        self,
        spans: Sequence[ArgusSpan],
        expected_tool_names: set[str],
    ) -> float:
        """Measure tool selection accuracy: ratio of valid distinct tools used to expected tools.

        Returns:
            Score between 0.0 and 1.0.
        """
        if not expected_tool_names:
            return 1.0

        used_tools = {
            s.name.replace("tool:", "")
            for s in spans
            if s.span_kind == SpanKind.TOOL
        }

        matched = used_tools & expected_tool_names
        return min(1.0, max(0.0, len(matched) / len(expected_tool_names)))

    def evaluate_task_completion(
        self,
        spans: Sequence[ArgusSpan],
        goal_keywords: set[str] | None = None,
    ) -> tuple[bool, float]:
        """Determine whether the agent trajectory completed successfully without unhandled errors.

        Returns:
            (is_completed, completion_score)
        """
        if not spans:
            return False, 0.0

        # Check for unhandled fatal errors or crash tags
        has_errors = any(
            "error" in str(s.output_payload).lower() or s.attributes.get("status") == "error"
            for s in spans
        )

        root_spans = [s for s in spans if s.parent_span_id is None]
        last_root = root_spans[-1] if root_spans else spans[-1]
        output_str = str(last_root.output_payload).lower()

        # Keyword matching on goal deliverables if provided
        if goal_keywords:
            matched_keywords = sum(1 for kw in goal_keywords if kw.lower() in output_str)
            keyword_ratio = matched_keywords / len(goal_keywords)
        else:
            keyword_ratio = 1.0

        score = 0.0 if has_errors else min(1.0, max(0.0, keyword_ratio))
        is_successful = (not has_errors) and (score >= 0.70)

        return is_successful, round(score, 4)
