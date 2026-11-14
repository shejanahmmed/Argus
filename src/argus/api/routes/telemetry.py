"""Telemetry ingestion, query, and normalizer endpoints for Argus."""

from __future__ import annotations

import contextlib
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.core.schemas import AgentSession, ArgusSpan, SessionStatus
from argus.core.tenancy import TenantContext
from argus.ingestors.cloudwatch_logs import CloudWatchLogIngestor, CorrelatedContainerLog
from argus.ingestors.otlp_receiver import OtlpSpanIngestor

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry"])


class IngestSpansRequest(BaseModel):
    spans: list[ArgusSpan] = Field(default_factory=list)


class IngestSpansResponse(BaseModel):
    status: str = "ok"
    ingested_count: int
    tripped_circuit_breaker: bool = False
    warning: str | None = None


class CloudWatchIngestRequest(BaseModel):
    log_events: list[dict[str, Any]] = Field(default_factory=list)


class CloudWatchIngestResponse(BaseModel):
    total_logs: int
    anomalies_count: int
    correlated_trace_count: int
    logs: list[dict[str, Any]]


@router.post("/spans", response_model=IngestSpansResponse)
async def ingest_spans(
    payload: IngestSpansRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> IngestSpansResponse:
    """Ingest a batch of Argus telemetry spans, enforcing budget and loop detection."""
    if not payload.spans:
        return IngestSpansResponse(ingested_count=0)

    tripped = False
    warning_msg: str | None = None

    for span in payload.spans:
        ctx.assert_same_tenant(span.tenant_id, span.workspace_id)

        # Budget reservation if cost present
        if span.cost_usd > 0.0:
            budget_verdict = await container.budget_guard.evaluate_and_reserve(
                ctx=ctx,
                session_id=span.session_id,
                requested_usd=span.cost_usd,
                hard_cap_usd=100.0,
            )
            if budget_verdict.tripped:
                tripped = True
                warning_msg = budget_verdict.diagnostic_message
                await container.event_bus.publish(
                    ctx,
                    channel="governance.circuit_breaker",
                    event={
                        "session_id": str(span.session_id),
                        "reason": budget_verdict.reason.value,
                        "detail": budget_verdict.diagnostic_message,
                    },
                )
                with contextlib.suppress(Exception):
                    await container.control_store.transition_session(
                        ctx=ctx,
                        session_id=span.session_id,
                        expected_status=SessionStatus.RUNNING,
                        next_status=SessionStatus.TRIPPED_BUDGET,
                    )

        # Loop detection evaluation
        tool_name = (
            str(span.attributes.get("tool_name", ""))
            if "tool_name" in span.attributes
            else None
        )
        thought_text = (
            str(span.output_payload.get("thought", ""))
            or str(span.output_payload.get("content", ""))
        )

        if tool_name or thought_text:
            loop_verdict = container.loop_detector.evaluate_step(
                session_id=str(span.session_id),
                tool_name=tool_name,
                tool_args=span.input_payload if tool_name else None,
                thought_text=thought_text,
            )
            if loop_verdict.tripped:
                tripped = True
                warning_msg = loop_verdict.diagnostic_message
                await container.event_bus.publish(
                    ctx,
                    channel="governance.circuit_breaker",
                    event={
                        "session_id": str(span.session_id),
                        "reason": loop_verdict.reason.value,
                        "similarity_score": loop_verdict.similarity_score,
                        "detail": loop_verdict.diagnostic_message,
                    },
                )
                with contextlib.suppress(Exception):
                    await container.control_store.transition_session(
                        ctx=ctx,
                        session_id=span.session_id,
                        expected_status=SessionStatus.RUNNING,
                        next_status=SessionStatus.TRIPPED_LOOP,
                    )

    # Persist spans in trace store
    count = await container.trace_store.append_spans(ctx, payload.spans)

    # Publish real-time telemetry event for WebSocket clients
    await container.event_bus.publish(
        ctx,
        channel="telemetry.spans",
        event={
            "count": count,
            "session_id": str(payload.spans[0].session_id),
            "trace_id": str(payload.spans[0].trace_id),
            "latest_span_id": str(payload.spans[-1].span_id),
            "dotted_order": payload.spans[-1].dotted_order,
        },
    )

    return IngestSpansResponse(
        ingested_count=count,
        tripped_circuit_breaker=tripped,
        warning=warning_msg,
    )


@router.post("/otlp", response_model=IngestSpansResponse)
async def ingest_otlp(
    payload: dict[str, Any],
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
    default_session_id: uuid.UUID | None = None,
) -> IngestSpansResponse:
    """Normalize and ingest raw OpenTelemetry GenAI JSON traces."""
    ingestor = OtlpSpanIngestor()
    sess_id = default_session_id or uuid.uuid4()
    raw_spans = payload.get("spans", [payload]) if isinstance(payload, dict) else []
    spans = ingestor.parse_span_batch(ctx, raw_spans, default_session_id=sess_id)
    if not spans:
        return IngestSpansResponse(ingested_count=0)

    return await ingest_spans(
        payload=IngestSpansRequest(spans=spans),
        ctx=ctx,
        container=container,
    )


@router.post("/cloudwatch", response_model=CloudWatchIngestResponse)
async def ingest_cloudwatch(
    payload: CloudWatchIngestRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> CloudWatchIngestResponse:
    """Ingest, parse, and correlate AWS CloudWatch / container log streams."""
    ingestor = CloudWatchLogIngestor()
    parsed_logs: list[CorrelatedContainerLog] = ingestor.parse_batch(payload.log_events)

    anomalies = [log for log in parsed_logs if log.is_container_anomaly]
    correlated = [log for log in parsed_logs if log.trace_id is not None]

    if parsed_logs:
        await container.event_bus.publish(
            ctx,
            channel="telemetry.cloudwatch",
            event={
                "total_logs": len(parsed_logs),
                "anomalies_count": len(anomalies),
                "correlated_count": len(correlated),
            },
        )

    return CloudWatchIngestResponse(
        total_logs=len(parsed_logs),
        anomalies_count=len(anomalies),
        correlated_trace_count=len(correlated),
        logs=[
            {
                "log_id": str(log.log_id),
                "timestamp": log.timestamp.isoformat(),
                "log_group": log.log_group,
                "log_stream": log.log_stream,
                "severity": log.severity,
                "message": log.message,
                "is_container_anomaly": log.is_container_anomaly,
                "trace_id": str(log.trace_id) if log.trace_id else None,
                "span_id": str(log.span_id) if log.span_id else None,
            }
            for log in parsed_logs
        ],
    )


@router.get("/sessions", response_model=list[AgentSession])
async def list_sessions(
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[AgentSession]:
    """List all agent sessions within the caller's workspace."""
    return await container.control_store.list_sessions(ctx)


@router.get("/sessions/{session_id}/spans", response_model=list[ArgusSpan])
async def get_session_spans(
    session_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[ArgusSpan]:
    """Retrieve all telemetry spans for a session ordered chronologically by dotted_order."""
    return await container.trace_store.get_session_spans(ctx, session_id)


@router.get("/traces/{root_dotted_order}", response_model=list[ArgusSpan])
async def get_trace_tree(
    root_dotted_order: str,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[ArgusSpan]:
    """Retrieve an ordered hierarchical trace subtree using dotted_order prefix scan."""
    return await container.trace_store.get_trace_subtree(ctx, root_dotted_order)
