"""Arize Phoenix evaluation and OpenInference conversion bridge.

Provides bi-directional schema translation between ArgusSpan entities and Arize Phoenix
OpenInference span schemas, facilitating LLM evaluation and notebook analytics.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from argus.core.schemas import ArgusSpan


class ArizePhoenixBridge:
    """Translation bridge to format Argus telemetry for Arize Phoenix evaluations."""

    def to_openinference_dict(self, span: ArgusSpan) -> dict[str, Any]:
        """Convert a single ArgusSpan into an OpenInference-compliant dictionary."""
        return {
            "context.span_id": str(span.span_id),
            "context.trace_id": str(span.trace_id),
            "parent_id": str(span.parent_span_id) if span.parent_span_id else None,
            "name": span.name,
            "span_kind": span.span_kind.value,
            "start_time": span.started_at.isoformat(),
            "end_time": span.ended_at.isoformat() if span.ended_at else None,
            "status_code": "OK",
            "attributes": {
                "openinference.span.kind": span.span_kind.value,
                "input.value": json.dumps(span.input_payload, default=str),
                "output.value": json.dumps(span.output_payload, default=str),
                "llm.model_name": span.model_name,
                "llm.token_count.prompt": span.prompt_tokens,
                "llm.token_count.completion": span.completion_tokens,
                "llm.token_count.total": span.prompt_tokens + span.completion_tokens,
                "argus.cost_usd": span.cost_usd,
                "argus.dotted_order": span.dotted_order,
                "argus.framework": span.framework.value,
                "argus.redacted": span.redacted,
                **span.attributes,
            },
        }

    def to_dataframe_records(self, spans: Sequence[ArgusSpan]) -> list[dict[str, Any]]:
        """Flatten a sequence of ArgusSpans into tabular records ready for pandas/polars."""
        records: list[dict[str, Any]] = []
        for s in spans:
            rec = {
                "span_id": str(s.span_id),
                "trace_id": str(s.trace_id),
                "parent_id": str(s.parent_span_id) if s.parent_span_id else None,
                "dotted_order": s.dotted_order,
                "name": s.name,
                "kind": s.span_kind.value,
                "model": s.model_name,
                "prompt_tokens": s.prompt_tokens,
                "completion_tokens": s.completion_tokens,
                "total_tokens": s.prompt_tokens + s.completion_tokens,
                "cost_usd": s.cost_usd,
                "latency_ms": s.latency_ms,
                "started_at": s.started_at,
                "ended_at": s.ended_at,
                "redacted": s.redacted,
            }
            records.append(rec)
        return records
