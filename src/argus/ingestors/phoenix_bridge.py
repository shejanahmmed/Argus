"""Arize Phoenix evaluation and OpenInference conversion bridge.

Provides bi-directional schema translation between ArgusSpan entities and Arize Phoenix
OpenInference span schemas, facilitating LLM evaluation, dataframe analytics, and offline
benchmark datasets (hallucination, tool calling, trajectory scoring).
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from argus.core.ids import build_dotted_order, new_uuid7, parse_dotted_order
from argus.core.schemas import (
    AgentFramework,
    ArgusSpan,
    EvalDatasetType,
    OperationName,
    PhoenixEvalDatasets,
    SpanKind,
)


class ArizePhoenixBridge:
    """Translation bridge to format Argus telemetry for Arize Phoenix evaluations and DataFrames."""

    @staticmethod
    def _detect_error(span: ArgusSpan) -> tuple[bool, str | None]:
        """Detect whether a span completed with an error or exception."""
        if "error" in span.attributes and bool(span.attributes["error"]):
            return True, str(span.attributes["error"])
        if "exception.message" in span.attributes and bool(span.attributes["exception.message"]):
            return True, str(span.attributes["exception.message"])
        if "failed" in span.attributes and bool(span.attributes["failed"]):
            return True, str(span.attributes.get("failure_reason") or "Span marked as failed")

        out = span.output_payload
        if isinstance(out, dict):
            if "error" in out and bool(out["error"]):
                return True, str(out["error"])
            if "exception" in out and bool(out["exception"]):
                return True, str(out["exception"])

        return False, None

    def to_openinference_dict(self, span: ArgusSpan) -> dict[str, Any]:
        """Convert a single ArgusSpan into an OpenInference-compliant dictionary."""
        is_err, err_msg = self._detect_error(span)
        status_code = "ERROR" if is_err else "OK"

        input_str = (
            json.dumps(span.input_payload, default=str)
            if isinstance(span.input_payload, dict)
            else str(span.input_payload)
        )
        output_str = (
            json.dumps(span.output_payload, default=str)
            if isinstance(span.output_payload, dict)
            else str(span.output_payload)
        )

        attributes: dict[str, Any] = {
            "openinference.span.kind": span.span_kind.value,
            "input.value": input_str,
            "input.mime_type": "application/json",
            "output.value": output_str,
            "output.mime_type": "application/json",
            "session.id": str(span.session_id),
            "argus.cost_usd": span.cost_usd,
            "argus.latency_ms": span.latency_ms,
            "argus.ttft_ms": span.ttft_ms,
            "argus.dotted_order": span.dotted_order,
            "argus.framework": span.framework.value,
            "argus.tenant_id": span.tenant_id,
            "argus.workspace_id": span.workspace_id,
            "argus.redacted": span.redacted,
            "argus.state_diff_count": len(span.state_diff),
            **span.attributes,
        }

        has_tokens = (span.prompt_tokens + span.completion_tokens) > 0
        if span.span_kind == SpanKind.LLM or span.model_name or has_tokens:
            attributes["llm.model_name"] = span.model_name
            if span.provider_name:
                attributes["llm.provider"] = span.provider_name
            attributes["llm.token_count.prompt"] = span.prompt_tokens
            attributes["llm.token_count.completion"] = span.completion_tokens
            attributes["llm.token_count.total"] = span.prompt_tokens + span.completion_tokens

        elif span.span_kind == SpanKind.TOOL:
            tool_name = (
                span.attributes.get("tool.name")
                or span.attributes.get("tool_name")
                or span.name
            )
            attributes["tool.name"] = str(tool_name)
            tool_desc = span.attributes.get("tool.description") or span.attributes.get(
                "tool_description"
            )
            if tool_desc:
                attributes["tool.description"] = str(tool_desc)
            attributes["tool.parameters"] = input_str

        elif (
            span.span_kind == SpanKind.RETRIEVER
            and isinstance(span.output_payload, dict)
            and "documents" in span.output_payload
        ):
            attributes["retrieval.documents"] = span.output_payload["documents"]

        if is_err and err_msg:
            attributes["exception.message"] = err_msg
            attributes["exception.type"] = str(
                span.attributes.get("exception.type") or "RuntimeError"
            )

        return {
            "context.span_id": str(span.span_id),
            "context.trace_id": str(span.trace_id),
            "parent_id": str(span.parent_span_id) if span.parent_span_id else None,
            "name": span.name,
            "span_kind": span.span_kind.value,
            "start_time": span.started_at.isoformat(),
            "end_time": span.ended_at.isoformat() if span.ended_at else None,
            "status_code": status_code,
            "status_message": err_msg,
            "attributes": attributes,
        }

    def to_dataframe_records(self, spans: Sequence[ArgusSpan]) -> list[dict[str, Any]]:
        """Flatten a sequence of ArgusSpans into tabular records ready for pandas/polars DataFrames.

        Conforms strictly to the columns produced by px.Client().get_spans_dataframe().
        """
        records: list[dict[str, Any]] = []
        for s in spans:
            is_err, err_msg = self._detect_error(s)
            tool_name: str | None = None
            if s.span_kind == SpanKind.TOOL:
                tool_name = str(
                    s.attributes.get("tool.name")
                    or s.attributes.get("tool_name")
                    or s.name
                )

            rec = {
                "span_id": str(s.span_id),
                "trace_id": str(s.trace_id),
                "parent_id": str(s.parent_span_id) if s.parent_span_id else None,
                "dotted_order": s.dotted_order,
                "name": s.name,
                "span_kind": s.span_kind.value,
                "status_code": "ERROR" if is_err else "OK",
                "status_message": err_msg,
                "start_time": s.started_at.isoformat(),
                "end_time": s.ended_at.isoformat() if s.ended_at else None,
                "latency_ms": s.latency_ms,
                "model_name": s.model_name,
                "provider_name": s.provider_name,
                "prompt_tokens": s.prompt_tokens,
                "completion_tokens": s.completion_tokens,
                "total_tokens": s.prompt_tokens + s.completion_tokens,
                "cost_usd": s.cost_usd,
                "input_value": json.dumps(s.input_payload, default=str),
                "output_value": json.dumps(s.output_payload, default=str),
                "session_id": str(s.session_id),
                "framework": s.framework.value,
                "attributes.openinference.span.kind": s.span_kind.value,
                "attributes.llm.model_name": s.model_name,
                "attributes.tool.name": tool_name,
                "attributes.argus.cost_usd": s.cost_usd,
            }
            records.append(rec)
        return records

    def to_dataframe_csv(self, spans: Sequence[ArgusSpan]) -> str:
        """Convert a sequence of ArgusSpans into an RFC 4180 CSV string for instant download."""
        records = self.to_dataframe_records(spans)
        if not records:
            return ""

        output = io.StringIO()
        fieldnames = list(records[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)
        return output.getvalue()

    def generate_eval_datasets(
        self,
        spans: Sequence[ArgusSpan],
        eval_type: EvalDatasetType = EvalDatasetType.ALL,
    ) -> PhoenixEvalDatasets:
        """Extract evaluation records for Hallucination, Tool Calling, and Trajectories."""
        hallucination_records: list[dict[str, Any]] = []
        tool_calling_records: list[dict[str, Any]] = []
        trajectory_records: list[dict[str, Any]] = []

        # 1. Hallucination / Groundedness Records
        if eval_type in (EvalDatasetType.ALL, EvalDatasetType.HALLUCINATION):
            contexts: list[str] = []
            for s in spans:
                if s.span_kind in (SpanKind.RETRIEVER, SpanKind.TOOL):
                    out_str = json.dumps(s.output_payload, default=str)
                    if out_str and out_str != "{}":
                        contexts.append(out_str)
            combined_context = "\n---\n".join(contexts[:5]) if contexts else ""

            for s in spans:
                if s.span_kind == SpanKind.LLM:
                    hallucination_records.append({
                        "span_id": str(s.span_id),
                        "query": json.dumps(s.input_payload, default=str),
                        "context": combined_context,
                        "response": json.dumps(s.output_payload, default=str),
                        "model_name": s.model_name,
                        "latency_ms": s.latency_ms,
                        "cost_usd": s.cost_usd,
                    })

        # 2. Tool Calling Accuracy Records
        if eval_type in (EvalDatasetType.ALL, EvalDatasetType.TOOL_CALLING):
            for s in spans:
                if s.span_kind == SpanKind.TOOL:
                    is_err, err_msg = self._detect_error(s)
                    tool_name = (
                        s.attributes.get("tool.name")
                        or s.attributes.get("tool_name")
                        or s.name
                    )
                    tool_calling_records.append({
                        "span_id": str(s.span_id),
                        "tool_name": str(tool_name),
                        "arguments": s.input_payload,
                        "output": s.output_payload,
                        "status": "FAILED" if is_err else "SUCCESS",
                        "error": err_msg,
                        "latency_ms": s.latency_ms,
                        "cost_usd": s.cost_usd,
                    })

        # 3. Agent Trajectory Scoring Records
        if eval_type in (EvalDatasetType.ALL, EvalDatasetType.TRAJECTORY):
            cum_cost = 0.0
            for idx, s in enumerate(spans):
                cum_cost += s.cost_usd
                is_err, err_msg = self._detect_error(s)
                trajectory_records.append({
                    "step_index": idx,
                    "span_id": str(s.span_id),
                    "dotted_order": s.dotted_order,
                    "name": s.name,
                    "kind": s.span_kind.value,
                    "operation_name": s.operation_name.value,
                    "model_name": s.model_name,
                    "latency_ms": s.latency_ms,
                    "cost_usd": s.cost_usd,
                    "cumulative_cost_usd": round(cum_cost, 6),
                    "state_mutation_count": len(s.state_diff),
                    "has_error": is_err,
                    "error_message": err_msg,
                })

        return PhoenixEvalDatasets(
            hallucination_records=hallucination_records,
            tool_calling_records=tool_calling_records,
            trajectory_records=trajectory_records,
        )

    def from_openinference_dict(
        self,
        raw: dict[str, Any],
        tenant_id: str,
        workspace_id: str,
        session_id: uuid.UUID,
        trace_id: uuid.UUID,
        dotted_order: str,
    ) -> ArgusSpan:
        """Convert an inbound OpenInference span dictionary into a typed ArgusSpan."""
        raw_attributes = raw.get("attributes", {})
        if not isinstance(raw_attributes, dict):
            raw_attributes = {}

        # 1. Parse span ID
        span_id_val = raw.get("context.span_id") or raw.get("span_id")
        span_id = new_uuid7()
        if span_id_val:
            try:
                candidate = uuid.UUID(str(span_id_val))
                if candidate.version == 7:
                    span_id = candidate
                else:
                    raw_attributes["openinference.external_span_id"] = str(span_id_val)
            except ValueError:
                raw_attributes["openinference.external_span_id"] = str(span_id_val)

        # 2. Parse parent ID
        parent_id_val = raw.get("parent_id")
        parent_id: uuid.UUID | None = None
        if parent_id_val:
            try:
                candidate_pid = uuid.UUID(str(parent_id_val))
                if candidate_pid.version == 7:
                    parent_id = candidate_pid
                else:
                    raw_attributes["openinference.external_parent_id"] = str(parent_id_val)
            except ValueError:
                raw_attributes["openinference.external_parent_id"] = str(parent_id_val)

        # 3. Parse Timestamps
        def parse_dt(v: Any) -> datetime:
            if isinstance(v, str):
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(UTC)
                except ValueError:
                    pass
            return datetime.now(UTC)

        started_at = parse_dt(raw.get("start_time"))
        ended_at = parse_dt(raw.get("end_time")) if raw.get("end_time") else None
        latency_ms = (
            (ended_at - started_at).total_seconds() * 1000.0
            if ended_at and ended_at >= started_at
            else 0.0
        )

        # 4. Construct compliant dotted_order
        candidate_order = raw.get("dotted_order") or dotted_order
        valid_dotted_order: str
        try:
            parsed = parse_dotted_order(candidate_order)
            if parsed[-1][1] == span_id:
                valid_dotted_order = candidate_order
            else:
                valid_dotted_order = build_dotted_order(
                    started_at=started_at,
                    span_id=span_id,
                    parent_dotted_order=raw.get("parent_dotted_order"),
                )
        except Exception:
            valid_dotted_order = build_dotted_order(
                started_at=started_at,
                span_id=span_id,
                parent_dotted_order=raw.get("parent_dotted_order"),
            )

        def get_attr(key: str, default: Any = None) -> Any:
            if key in raw_attributes and raw_attributes[key] is not None:
                return raw_attributes[key]
            if key in raw and raw[key] is not None:
                return raw[key]
            return default

        # 5. Map Span Kind
        kind_str = str(
            get_attr("openinference.span.kind")
            or get_attr("span_kind")
            or "CHAIN"
        ).upper()

        kind_map = {
            "AGENT": SpanKind.AGENT,
            "CHAIN": SpanKind.CHAIN,
            "LLM": SpanKind.LLM,
            "TOOL": SpanKind.TOOL,
            "RETRIEVER": SpanKind.RETRIEVER,
            "EMBEDDING": SpanKind.EMBEDDING,
            "GUARDRAIL": SpanKind.GUARDRAIL,
        }
        span_kind = kind_map.get(kind_str, SpanKind.CHAIN)

        # 6. Map Operation Name
        op_map = {
            SpanKind.LLM: OperationName.CHAT,
            SpanKind.TOOL: OperationName.EXECUTE_TOOL,
            SpanKind.RETRIEVER: OperationName.RETRIEVE,
            SpanKind.AGENT: OperationName.INVOKE_AGENT,
        }
        operation_name = op_map.get(span_kind, OperationName.STATE_TRANSITION)

        # 7. Parse Payloads
        def parse_payload(v: Any) -> dict[str, Any]:
            if isinstance(v, dict):
                return v
            if isinstance(v, str):
                try:
                    loaded = json.loads(v)
                    if isinstance(loaded, dict):
                        return loaded
                    return {"value": loaded}
                except Exception:
                    return {"value": v}
            return {}

        input_payload = parse_payload(get_attr("input.value") or get_attr("input"))
        output_payload = parse_payload(get_attr("output.value") or get_attr("output"))

        # 8. Extract Tokens, Model, & Cost
        prompt_tokens = int(get_attr("llm.token_count.prompt", 0) or 0)
        completion_tokens = int(get_attr("llm.token_count.completion", 0) or 0)
        model_name = get_attr("llm.model_name") or get_attr("model")
        provider_name = get_attr("llm.provider") or get_attr("provider")
        cost_usd = float(get_attr("argus.cost_usd", 0.0) or get_attr("cost_usd", 0.0) or 0.0)

        # 9. Clean attributes
        merged_attrs: dict[str, Any] = {**raw, **raw_attributes}
        clean_attributes: dict[str, str | int | float | bool] = {}
        for k, v in merged_attrs.items():
            if k in (
                "context.span_id",
                "span_id",
                "context.trace_id",
                "trace_id",
                "parent_id",
                "name",
                "start_time",
                "end_time",
                "input",
                "output",
                "attributes",
            ):
                continue
            if isinstance(v, (str, int, float, bool)):
                clean_attributes[k] = v

        name = str(raw.get("name") or f"openinference_{span_kind.value.lower()}")

        return ArgusSpan(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_id,
            dotted_order=valid_dotted_order,
            name=name,
            span_kind=span_kind,
            operation_name=operation_name,
            framework=AgentFramework.CUSTOM,
            model_name=str(model_name) if model_name else None,
            provider_name=str(provider_name) if provider_name else None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            input_payload=input_payload,
            output_payload=output_payload,
            attributes=clean_attributes,
            started_at=started_at,
            ended_at=ended_at,
        )
