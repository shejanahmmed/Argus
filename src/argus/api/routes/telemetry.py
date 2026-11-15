"""Telemetry ingestion, query, and normalizer endpoints for Argus."""

from __future__ import annotations

import contextlib
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.core.ids import new_uuid7
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    ArgusSpan,
    CircuitBreakerAction,
    CloudWatchIngestRequest,
    CloudWatchIngestResponse,
    CloudWatchQueryResponse,
    CorrelatedContainerLog,
    SessionStatus,
)
from argus.core.tenancy import TenantContext
from argus.ingestors.cloudwatch_logs import CloudWatchLogIngestor
from argus.ingestors.otlp_receiver import OtlpSpanIngestor

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry"])


class CreateSessionRequest(BaseModel):
    session_id: uuid.UUID | None = None
    workflow_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    framework: AgentFramework = Field(default=AgentFramework.LANGGRAPH)
    budget_cap_usd: float = Field(default=50.0, gt=0.0)


class IngestSpansRequest(BaseModel):
    spans: list[ArgusSpan] = Field(default_factory=list)


class IngestSpansResponse(BaseModel):
    status: str = "ok"
    ingested_count: int
    tripped_circuit_breaker: bool = False
    warning: str | None = None


def _serialize_container_log(log: CorrelatedContainerLog) -> dict[str, Any]:
    return {
        "log_id": str(log.log_id),
        "timestamp": log.timestamp.isoformat(),
        "log_group": log.log_group,
        "log_stream": log.log_stream,
        "severity": log.severity,
        "message": log.message,
        "is_container_anomaly": log.is_container_anomaly,
        "anomaly_type": log.anomaly_type.value if log.anomaly_type else None,
        "trace_id": str(log.trace_id) if log.trace_id else None,
        "span_id": str(log.span_id) if log.span_id else None,
        "session_id": str(log.session_id) if log.session_id else None,
    }


@router.post("/sessions", response_model=AgentSession)
async def create_session(
    payload: CreateSessionRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> AgentSession:
    """Register a new governed autonomous agent session."""
    sid = (
        payload.session_id
        if (payload.session_id and payload.session_id.version == 7)
        else new_uuid7()
    )
    session = AgentSession(
        session_id=sid,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        workflow_id=payload.workflow_id,
        agent_name=payload.agent_name,
        framework=payload.framework,
        budget_cap_usd=payload.budget_cap_usd,
    )
    created = await container.control_store.create_session(ctx, session)
    await container.event_bus.publish(
        ctx,
        channel="telemetry.sessions",
        event={
            "session_id": str(created.session_id),
            "agent_name": created.agent_name,
            "status": created.status.value,
        },
    )
    return created


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
    processed_spans: list[ArgusSpan] = []

    for span in payload.spans:
        ctx.assert_same_tenant(span.tenant_id, span.workspace_id)

        # Budget reservation and session cost synchronization
        if span.cost_usd > 0.0:
            hard_cap = 100.0
            with contextlib.suppress(Exception):
                existing_sess = await container.control_store.get_session(ctx, span.session_id)
                hard_cap = existing_sess.budget_cap_usd
                await container.control_store.add_session_cost(ctx, span.session_id, span.cost_usd)

            budget_verdict = await container.budget_guard.evaluate_and_reserve(
                ctx=ctx,
                session_id=span.session_id,
                requested_usd=span.cost_usd,
                hard_cap_usd=hard_cap,
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

        current_span = span
        if tool_name or thought_text:
            loop_verdict = container.loop_detector.evaluate_step(
                session_id=str(span.session_id),
                tenant_id=ctx.tenant_id,
                tool_name=tool_name,
                tool_args=span.input_payload if tool_name else None,
                thought_text=thought_text,
                step_cost_usd=span.cost_usd,
            )
            if loop_verdict.tripped:
                tripped = True
                warning_msg = loop_verdict.diagnostic_message

                # Annotate span attributes with loop trip diagnostics
                updated_attrs = dict(span.attributes)
                updated_attrs["loop_tripped"] = "true"
                updated_attrs["loop_reason"] = loop_verdict.reason.value
                if loop_verdict.trip_tier is not None:
                    updated_attrs["loop_tier"] = str(loop_verdict.trip_tier)
                if loop_verdict.wasted_cost_usd > 0.0:
                    updated_attrs["wasted_cost_usd"] = str(loop_verdict.wasted_cost_usd)
                current_span = span.model_copy(update={"attributes": updated_attrs})

                await container.event_bus.publish(
                    ctx,
                    channel="governance.circuit_breaker",
                    event={
                        "session_id": str(span.session_id),
                        "reason": loop_verdict.reason.value,
                        "trip_tier": loop_verdict.trip_tier,
                        "similarity_score": loop_verdict.similarity_score,
                        "hamming_distance": loop_verdict.hamming_distance,
                        "wasted_cost_usd": loop_verdict.wasted_cost_usd,
                        "repeated_count": loop_verdict.repeated_count,
                        "recommended_action": loop_verdict.recommended_action.value,
                        "nudge_instruction": loop_verdict.nudge_instruction,
                        "detail": loop_verdict.diagnostic_message,
                    },
                )

                if loop_verdict.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2:
                    with contextlib.suppress(Exception):
                        await container.control_store.transition_session(
                            ctx=ctx,
                            session_id=span.session_id,
                            expected_status=SessionStatus.RUNNING,
                            next_status=SessionStatus.TRIPPED_LOOP,
                        )
                elif loop_verdict.recommended_action == CircuitBreakerAction.TERMINATE:
                    with contextlib.suppress(Exception):
                        await container.control_store.transition_session(
                            ctx=ctx,
                            session_id=span.session_id,
                            expected_status=SessionStatus.RUNNING,
                            next_status=SessionStatus.TERMINATED,
                        )

        processed_spans.append(current_span)

    # Persist spans in trace store
    count = await container.trace_store.append_spans(ctx, processed_spans)

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
    sess_id = (
        default_session_id
        if (default_session_id and default_session_id.version == 7)
        else new_uuid7()
    )
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
    parsed_logs: list[CorrelatedContainerLog] = ingestor.parse_batch(
        payload.log_events,
        default_log_group=payload.default_log_group,
        default_log_stream=payload.default_log_stream,
    )

    anomalies = [log for log in parsed_logs if log.is_container_anomaly]
    correlated = [log for log in parsed_logs if log.trace_id is not None]
    serialized_logs = [_serialize_container_log(log) for log in parsed_logs]

    if parsed_logs:
        max_buffer = container.settings.container_log_ring_buffer_size
        container.container_logs = (parsed_logs + container.container_logs)[:max_buffer]
        await container.event_bus.publish(
            ctx,
            channel="telemetry.cloudwatch",
            event={
                "total_logs": len(parsed_logs),
                "anomalies_count": len(anomalies),
                "correlated_count": len(correlated),
                "logs": serialized_logs,
            },
        )
        if anomalies:
            await container.event_bus.publish(
                ctx,
                channel="governance.circuit_breaker",
                event={
                    "event_type": "CONTAINER_ANOMALY_DETECTED",
                    "anomalies_count": len(anomalies),
                    "anomalies": [_serialize_container_log(a) for a in anomalies],
                },
            )

    return CloudWatchIngestResponse(
        total_logs=len(parsed_logs),
        anomalies_count=len(anomalies),
        correlated_trace_count=len(correlated),
        logs=parsed_logs,
    )


@router.get("/cloudwatch", response_model=list[dict[str, Any]])
async def list_cloudwatch_logs(
    container: Annotated[AppContainer, Depends(get_container)],
    trace_id: Annotated[uuid.UUID | None, Query()] = None,
    session_id: Annotated[uuid.UUID | None, Query()] = None,
    severity: Annotated[str | None, Query()] = None,
    anomalies_only: Annotated[bool, Query()] = False,
    correlated_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    """Retrieve recent correlated container / CloudWatch logs with optional filters."""
    logs = container.container_logs
    if trace_id is not None:
        logs = [log for log in logs if log.trace_id == trace_id]
    if session_id is not None:
        logs = [log for log in logs if log.session_id == session_id]
    if severity is not None:
        logs = [log for log in logs if log.severity.upper() == severity.upper()]
    if anomalies_only:
        logs = [log for log in logs if log.is_container_anomaly]
    if correlated_only:
        logs = [log for log in logs if log.trace_id is not None or log.session_id is not None]

    paginated = logs[offset : offset + limit]
    return [_serialize_container_log(log) for log in paginated]


@router.get("/cloudwatch/query", response_model=CloudWatchQueryResponse)
async def query_cloudwatch_logs(
    container: Annotated[AppContainer, Depends(get_container)],
    trace_id: Annotated[uuid.UUID | None, Query()] = None,
    session_id: Annotated[uuid.UUID | None, Query()] = None,
    severity: Annotated[str | None, Query()] = None,
    anomalies_only: Annotated[bool, Query()] = False,
    correlated_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CloudWatchQueryResponse:
    """Query recent correlated container logs with metadata and pagination."""
    logs = container.container_logs
    if trace_id is not None:
        logs = [log for log in logs if log.trace_id == trace_id]
    if session_id is not None:
        logs = [log for log in logs if log.session_id == session_id]
    if severity is not None:
        logs = [log for log in logs if log.severity.upper() == severity.upper()]
    if anomalies_only:
        logs = [log for log in logs if log.is_container_anomaly]
    if correlated_only:
        logs = [log for log in logs if log.trace_id is not None or log.session_id is not None]

    total_count = len(logs)
    anomalies_count = sum(1 for log in logs if log.is_container_anomaly)
    correlated_count = sum(
        1 for log in logs if log.trace_id is not None or log.session_id is not None
    )
    paginated = logs[offset : offset + limit]

    return CloudWatchQueryResponse(
        total_count=total_count,
        anomalies_count=anomalies_count,
        correlated_count=correlated_count,
        limit=limit,
        offset=offset,
        logs=paginated,
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


@router.get("/sessions/{session_id}/phoenix", response_model=dict[str, Any])
async def export_phoenix_openinference(
    session_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> dict[str, Any]:
    """Export session telemetry in Arize Phoenix OpenInference format and DataFrame records."""
    spans = await container.trace_store.get_session_spans(ctx, session_id)
    return {
        "session_id": str(session_id),
        "span_count": len(spans),
        "openinference_spans": [container.phoenix_bridge.to_openinference_dict(s) for s in spans],
        "dataframe_records": container.phoenix_bridge.to_dataframe_records(spans),
    }


@router.get("/traces/{root_dotted_order}", response_model=list[ArgusSpan])
async def get_trace_tree(
    root_dotted_order: str,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[ArgusSpan]:
    """Retrieve an ordered hierarchical trace subtree using dotted_order prefix scan."""
    return await container.trace_store.get_trace_subtree(ctx, root_dotted_order)
