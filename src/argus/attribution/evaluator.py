"""Zero-spend deterministic agent trajectory evaluation metrics."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from argus.core.schemas import ArgusSpan, SpanKind, TrajectoryEvaluationReport


class TrajectoryEvaluator:
    """Evaluates agent execution trajectories deterministically without external paid LLM APIs."""

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
            s.name.replace("tool:", "").strip()
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

    def evaluate_trajectory(
        self,
        spans: Sequence[ArgusSpan],
        *,
        tenant_id: str,
        workspace_id: str,
        session_id: uuid.UUID,
        expected_tool_names: set[str] | None = None,
        goal_keywords: set[str] | None = None,
    ) -> TrajectoryEvaluationReport:
        """Execute comprehensive deterministic trajectory evaluation across multi-step execution.

        Returns:
            Structured TrajectoryEvaluationReport detailing step metrics, tool matching,
            error diagnostics, and task completion verification.
        """
        total_steps = len(spans)
        llm_steps = sum(
            1 for s in spans if s.span_kind in (SpanKind.LLM, SpanKind.AGENT, SpanKind.CHAIN)
        )
        tool_steps = sum(
            1
            for s in spans
            if s.span_kind == SpanKind.TOOL or s.operation_name.value == "execute_tool"
        )

        # 1. Tool selection analysis
        used_tools_set: set[str] = {
            s.name.replace("tool:", "").strip()
            for s in spans
            if s.span_kind == SpanKind.TOOL
        }
        exp_tools_set: set[str] = expected_tool_names or set()

        matched_tools_set = used_tools_set & exp_tools_set if exp_tools_set else used_tools_set
        missing_tools_set = exp_tools_set - used_tools_set if exp_tools_set else set()
        unexpected_tools_set = used_tools_set - exp_tools_set if exp_tools_set else set()

        if exp_tools_set:
            tool_score = min(1.0, max(0.0, len(matched_tools_set) / len(exp_tools_set)))
        else:
            tool_score = 1.0

        # 2. Fatal error detection
        fatal_errors: list[str] = []
        for s in spans:
            status_attr = str(s.attributes.get("status", "")).lower()
            if status_attr == "error" or s.attributes.get("error"):
                fatal_errors.append(f"Span {s.span_id} ({s.name}) reported status=error")
            elif "error" in str(s.output_payload).lower():
                payload_str = str(s.output_payload)
                if any(
                    err_term in payload_str.lower()
                    for err_term in ("exception", "traceback", "status': 'error'", "failed")
                ):
                    fatal_errors.append(
                        f"Span {s.span_id} ({s.name}) contained fatal error payload"
                    )

        # 3. Deliverable and goal keyword verification
        root_spans = [s for s in spans if s.parent_span_id is None]
        last_root = root_spans[-1] if root_spans else (spans[-1] if spans else None)
        output_str = str(last_root.output_payload).lower() if last_root else ""

        matched_kws: list[str] = []
        if goal_keywords:
            for kw in sorted(goal_keywords):
                if kw.lower() in output_str:
                    matched_kws.append(kw)

        task_completed, comp_score = self.evaluate_task_completion(spans, goal_keywords)

        # 4. Diagnostic summary assembly
        if fatal_errors:
            diagnostic = (
                f"Trajectory failed with {len(fatal_errors)} fatal error(s) detected. "
                f"Completed {total_steps} step(s); task completion aborted."
            )
        elif task_completed:
            diagnostic = (
                f"Trajectory completed successfully ({comp_score * 100:.0f}% goal satisfaction). "
                f"Matched {len(matched_tools_set)}/{len(exp_tools_set) or len(used_tools_set)} "
                f"tools across {total_steps} execution step(s)."
            )
        else:
            diagnostic = (
                f"Trajectory in-progress or partially completed ({comp_score * 100:.0f}% goal "
                f"satisfaction). Met {len(matched_kws)}/{len(goal_keywords or [])} goal keywords."
            )

        return TrajectoryEvaluationReport(
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            total_steps=total_steps,
            llm_steps=llm_steps,
            tool_steps=tool_steps,
            expected_tools=sorted(exp_tools_set),
            used_tools=sorted(used_tools_set),
            matched_tools=sorted(matched_tools_set),
            missing_tools=sorted(missing_tools_set),
            unexpected_tools=sorted(unexpected_tools_set),
            tool_correctness_score=round(tool_score, 4),
            goal_keywords=sorted(goal_keywords) if goal_keywords else [],
            matched_keywords=sorted(matched_kws),
            task_completed=task_completed,
            task_completion_score=comp_score,
            fatal_errors_detected=fatal_errors,
            diagnostic_summary=diagnostic,
        )
