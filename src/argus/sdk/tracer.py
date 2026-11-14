"""Core cross-platform OpenTelemetry + OpenInference telemetry tracer.

Constructs strictly validated ArgusSpan objects with chronological UUIDv7 identifiers,
microsecond dotted_order hierarchy tracking, edge PII scrubbing, non-blocking export,
and fail-open local JSONL spooling.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from argus.core.ids import build_dotted_order, new_uuid7, utc_now
from argus.core.schemas import (
    AgentFramework,
    ArgusSpan,
    JsonPatchOp,
    OperationName,
    SpanKind,
)
from argus.core.tenancy import TenantContext
from argus.ports.repositories import TraceStore
from argus.sdk.context import (
    get_current_dotted_order,
    get_current_session_id,
    get_current_span_id,
    get_current_trace_id,
    scope_span,
)
from argus.security.redactor import EdgeRedactor

P = ParamSpec("P")
R = TypeVar("R")


class ArgusTracer:
    """Enterprise OpenTelemetry + OpenInference tracer for autonomous AI agents."""

    def __init__(
        self,
        *,
        trace_store: TraceStore,
        redactor: EdgeRedactor | None = None,
        default_framework: AgentFramework = AgentFramework.CUSTOM,
        spool_path: Path | str | None = Path(".argus_logs/spool_spans.jsonl"),
    ) -> None:
        self._store = trace_store
        self._redactor = redactor or EdgeRedactor()
        self._default_framework = default_framework
        self._spool_path = Path(spool_path) if spool_path is not None else None

    def _spool_failed_span(self, span: ArgusSpan) -> None:
        """Fail-open fallback: write span to local JSONL spool so agent runtime never crashes."""
        if self._spool_path is None:
            return
        try:
            self._spool_path.parent.mkdir(parents=True, exist_ok=True)
            with self._spool_path.open("a", encoding="utf-8") as handle:
                handle.write(span.model_dump_json() + "\n")
        except Exception:
            pass

    @asynccontextmanager
    async def start_span(
        self,
        ctx: TenantContext,
        *,
        name: str,
        span_kind: SpanKind,
        operation_name: OperationName,
        framework: AgentFramework | None = None,
        session_id: uuid.UUID | None = None,
        trace_id: uuid.UUID | None = None,
        parent_span_id: uuid.UUID | None = None,
        parent_dotted_order: str | None = None,
        input_payload: dict[str, Any] | None = None,
        model_name: str | None = None,
        provider_name: str | None = None,
    ) -> AsyncIterator[SpanBuilder]:
        """Async context manager creating, tracking, and publishing a validated ArgusSpan."""
        started_at = utc_now()
        span_id = new_uuid7()

        # Resolve session and trace from explicit arguments or ambient contextvars
        resolved_session_id = session_id or get_current_session_id()
        if resolved_session_id is None:
            raise ValueError(
                "No session_id provided and no ambient session active in context."
            )

        resolved_trace_id = trace_id or get_current_trace_id() or new_uuid7()
        resolved_parent_id = parent_span_id or get_current_span_id()
        resolved_parent_order = parent_dotted_order or get_current_dotted_order()

        # Build chronological dotted_order path
        dotted_order = build_dotted_order(
            started_at=started_at,
            span_id=span_id,
            parent_dotted_order=resolved_parent_order,
        )

        # Scrub input payload at the edge before recording
        cleaned_input, input_redacted = self._redactor.scrub_payload(input_payload or {})

        builder = SpanBuilder(
            name=name,
            span_kind=span_kind,
            operation_name=operation_name,
            framework=framework or self._default_framework,
            model_name=model_name,
            provider_name=provider_name,
            input_payload=cleaned_input,
            redacted=input_redacted,
        )

        with scope_span(span_id, dotted_order):
            try:
                yield builder
            finally:
                ended_at = utc_now()
                latency_ms = max(
                    0.0,
                    (ended_at - started_at).total_seconds() * 1000.0,
                )

                # Scrub output payload at the edge
                cleaned_output, output_redacted = self._redactor.scrub_payload(
                    builder.output_payload
                )
                total_redacted = builder.redacted or input_redacted or output_redacted

                span = ArgusSpan(
                    tenant_id=ctx.tenant_id,
                    workspace_id=ctx.workspace_id,
                    session_id=resolved_session_id,
                    trace_id=resolved_trace_id,
                    span_id=span_id,
                    parent_span_id=resolved_parent_id,
                    dotted_order=dotted_order,
                    name=builder.name,
                    span_kind=builder.span_kind,
                    operation_name=builder.operation_name,
                    framework=builder.framework,
                    model_name=builder.model_name,
                    provider_name=builder.provider_name,
                    prompt_tokens=builder.prompt_tokens,
                    completion_tokens=builder.completion_tokens,
                    cost_usd=builder.cost_usd,
                    ttft_ms=builder.ttft_ms,
                    latency_ms=latency_ms,
                    input_payload=builder.input_payload,
                    output_payload=cleaned_output,
                    state_diff=tuple(builder.state_diff),
                    attributes=builder.attributes,
                    redacted=total_redacted,
                    started_at=started_at,
                    ended_at=ended_at,
                )

                try:
                    await self._store.append_spans(ctx, [span])
                except Exception:
                    # Telemetry export must fail OPEN so observability outages never crash agents
                    self._spool_failed_span(span)

    def trace(
        self,
        ctx: TenantContext,
        *,
        name: str | None = None,
        span_kind: SpanKind = SpanKind.CHAIN,
        operation_name: OperationName = OperationName.STATE_TRANSITION,
        framework: AgentFramework | None = None,
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        """Decorator wrapping an async function in a traced ArgusSpan with PII redaction."""

        def _decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            span_name = name or func.__name__

            @functools.wraps(func)
            async def _wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                captured_in: dict[str, Any] = {
                    k: str(v) if not isinstance(v, (str, int, float, bool, dict, list)) else v
                    for k, v in kwargs.items()
                }
                async with self.start_span(
                    ctx,
                    name=span_name,
                    span_kind=span_kind,
                    operation_name=operation_name,
                    framework=framework,
                    input_payload=captured_in,
                ) as builder:
                    result = await func(*args, **kwargs)
                    if isinstance(result, dict):
                        builder.set_output(result)
                    else:
                        builder.set_output({"result": str(result)})
                    return result

            return _wrapper

        return _decorator


class SpanBuilder:
    """Mutable builder accessible within a start_span context block."""

    def __init__(
        self,
        *,
        name: str,
        span_kind: SpanKind,
        operation_name: OperationName,
        framework: AgentFramework,
        model_name: str | None,
        provider_name: str | None,
        input_payload: dict[str, Any],
        redacted: bool,
    ) -> None:
        self.name = name
        self.span_kind = span_kind
        self.operation_name = operation_name
        self.framework = framework
        self.model_name = model_name
        self.provider_name = provider_name
        self.input_payload = input_payload
        self.output_payload: dict[str, Any] = {}
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.cost_usd: float = 0.0
        self.ttft_ms: float | None = None
        self.state_diff: list[JsonPatchOp] = []
        self.attributes: dict[str, str | int | float | bool] = {}
        self.redacted = redacted

    def set_output(self, output: dict[str, Any]) -> None:
        """Set the output dictionary of the span."""
        self.output_payload = output

    def record_tokens(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        ttft_ms: float | None = None,
    ) -> None:
        """Record model inference metrics."""
        self.prompt_tokens += max(0, prompt_tokens)
        self.completion_tokens += max(0, completion_tokens)
        self.cost_usd += max(0.0, cost_usd)
        if ttft_ms is not None:
            self.ttft_ms = max(0.0, ttft_ms)

    def append_state_diff(self, op: str, path: str, value: Any = None) -> None:
        """Record an RFC 6902 state patch operation."""
        valid_ops = {"add", "remove", "replace", "move", "copy", "test"}
        if op not in valid_ops:
            raise ValueError(f"Invalid patch op: {op}")
        self.state_diff.append(
            JsonPatchOp(op=op, path=path, value=value)  # type: ignore[arg-type]
        )

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        """Add a custom metadata attribute."""
        self.attributes[key] = value
