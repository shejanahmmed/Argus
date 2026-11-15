"""OpenTelemetry (OTLP) and OpenInference JSON span ingestor.

Normalizes third-party OTLP/OpenInference JSON span batches into strongly typed ArgusSpan models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from argus.core.ids import build_dotted_order, new_uuid7, utc_now
from argus.core.pricing import estimate_token_cost_usd
from argus.core.schemas import (
    AgentFramework,
    ArgusSpan,
    OperationName,
    SpanKind,
)
from argus.core.tenancy import TenantContext
from argus.security.redactor import EdgeRedactor

# Mapping from external OpenInference / OTel span kinds to Argus SpanKind
_SPAN_KIND_MAP: dict[str, SpanKind] = {
    "AGENT": SpanKind.AGENT,
    "CHAIN": SpanKind.CHAIN,
    "LLM": SpanKind.LLM,
    "TOOL": SpanKind.TOOL,
    "RETRIEVER": SpanKind.RETRIEVER,
    "EMBEDDING": SpanKind.EMBEDDING,
    "GUARDRAIL": SpanKind.GUARDRAIL,
}


class OtlpSpanIngestor:
    """Ingestor normalizing standard OpenTelemetry / OpenInference JSON records."""

    def __init__(self, redactor: EdgeRedactor | None = None) -> None:
        self._redactor = redactor or EdgeRedactor()

    def parse_span_batch(
        self,
        ctx: TenantContext,
        raw_spans: list[dict[str, Any]],
        *,
        default_session_id: uuid.UUID,
    ) -> list[ArgusSpan]:
        """Convert a list of raw OTLP/OpenInference dictionary spans into ArgusSpan instances."""
        parsed_spans: list[ArgusSpan] = []

        for raw in raw_spans:
            # Identity and timing extraction
            raw_span_id = raw.get("span_id") or str(new_uuid7())
            span_id = (
                uuid.UUID(raw_span_id)
                if uuid.UUID(raw_span_id).version == 7
                else new_uuid7()
            )

            raw_trace_id = raw.get("trace_id") or str(new_uuid7())
            trace_id = (
                uuid.UUID(raw_trace_id)
                if uuid.UUID(raw_trace_id).version == 7
                else new_uuid7()
            )

            parent_id_raw = raw.get("parent_span_id")
            parent_span_id = (
                uuid.UUID(parent_id_raw)
                if parent_id_raw and uuid.UUID(parent_id_raw).version == 7
                else None
            )

            start_time_raw = raw.get("start_time")
            if isinstance(start_time_raw, (int, float)):
                started_at = datetime.fromtimestamp(start_time_raw, tz=UTC)
            elif isinstance(start_time_raw, str):
                started_at = datetime.fromisoformat(start_time_raw).astimezone(
                    UTC
                )
            else:
                started_at = utc_now()

            # Construct synthetic dotted_order if not present in payload
            parent_order = raw.get("parent_dotted_order")
            dotted_order = raw.get("dotted_order") or build_dotted_order(
                started_at=started_at,
                span_id=span_id,
                parent_dotted_order=parent_order,
            )

            # SpanKind and classification mapping
            raw_kind = str(
                raw.get("openinference.span.kind") or raw.get("span_kind") or "CHAIN"
            ).upper()
            span_kind = _SPAN_KIND_MAP.get(raw_kind, SpanKind.CHAIN)

            op_name = (
                OperationName.CHAT
                if span_kind == SpanKind.LLM
                else OperationName.EXECUTE_TOOL
                if span_kind == SpanKind.TOOL
                else OperationName.INVOKE_AGENT
            )

            model_name = raw.get("llm.model_name")
            p_tokens = int(raw.get("llm.token_count.prompt", 0))
            c_tokens = int(raw.get("llm.token_count.completion", 0))

            raw_cost = float(raw.get("cost_usd", 0.0))
            if raw_cost <= 0.0 and (p_tokens > 0 or c_tokens > 0):
                cost_usd = estimate_token_cost_usd(model_name, p_tokens, c_tokens)
            else:
                cost_usd = raw_cost

            raw_in = raw.get("input_payload") or {"value": raw.get("input.value", "")}
            raw_out = raw.get("output_payload") or {"value": raw.get("output.value", "")}

            clean_in, in_redacted = self._redactor.scrub_payload(
                raw_in if isinstance(raw_in, dict) else {"raw": str(raw_in)}
            )
            clean_out, out_redacted = self._redactor.scrub_payload(
                raw_out if isinstance(raw_out, dict) else {"raw": str(raw_out)}
            )

            span = ArgusSpan(
                tenant_id=ctx.tenant_id,
                workspace_id=ctx.workspace_id,
                session_id=default_session_id,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                dotted_order=dotted_order,
                name=str(raw.get("name", "otlp.span")),
                span_kind=span_kind,
                operation_name=op_name,
                framework=AgentFramework.CUSTOM,
                model_name=model_name,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                cost_usd=cost_usd,
                latency_ms=float(raw.get("latency_ms", 0.0)),
                input_payload=clean_in,
                output_payload=clean_out,
                redacted=bool(in_redacted or out_redacted),
                started_at=started_at,
            )
            parsed_spans.append(span)

        return parsed_spans
