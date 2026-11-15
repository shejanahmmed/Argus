"""Unit tests for CloudWatch log ingestion, OTLP ingestion, and Arize Phoenix bridge."""

from __future__ import annotations

import json

import pytest

from argus.core.ids import new_uuid7, utc_now
from argus.core.schemas import (
    AgentFramework,
    ArgusSpan,
    ContainerAnomalyType,
    OperationName,
    SpanKind,
)
from argus.core.tenancy import Role, TenantContext
from argus.ingestors.cloudwatch_logs import CloudWatchLogIngestor
from argus.ingestors.otlp_receiver import OtlpSpanIngestor
from argus.ingestors.phoenix_bridge import ArizePhoenixBridge


def test_cloudwatch_log_correlates_trace_and_flags_anomalies() -> None:
    ingestor = CloudWatchLogIngestor()
    trace_id = new_uuid7()
    span_id = new_uuid7()

    raw_event = {
        "logGroup": "/aws/ecs/ai-workers",
        "logStream": "worker-1",
        "timestamp": 1731630000000,
        "message": json.dumps(
            {
                "level": "ERROR",
                "trace_id": str(trace_id),
                "span_id": str(span_id),
                "msg": "Container fatal: Out of memory (exit code 137)",
            }
        ),
    }

    log = ingestor.parse_log_event(raw_event)
    assert log.trace_id == trace_id
    assert log.span_id == span_id
    assert log.is_container_anomaly is True
    assert log.anomaly_type == ContainerAnomalyType.EXIT_CODE_137
    assert log.severity == "ERROR"
    assert log.log_group == "/aws/ecs/ai-workers"


def test_cloudwatch_anomaly_taxonomy_classification() -> None:
    ingestor = CloudWatchLogIngestor()

    test_cases = [
        ("task timed out after 300.00 seconds executing tool", ContainerAnomalyType.WORKER_TIMEOUT),
        ("fatal error: runtime error: invalid memory address", ContainerAnomalyType.PANIC_CRASH),
        ("panic: segmentation violation in worker thread", ContainerAnomalyType.PANIC_CRASH),
        ("process received signal 9 (sigkill)", ContainerAnomalyType.SIGKILL),
        ("graceful shutdown timeout exceeded, sending sigterm", ContainerAnomalyType.SIGTERM),
        ("kernel: [12345.67] segfault at 000000000000", ContainerAnomalyType.SEGMENTATION_FAULT),
        ("cgroup out of memory: Killed process 42", ContainerAnomalyType.OOM_KILL),
    ]

    for message, expected_type in test_cases:
        log = ingestor.parse_log_event({"message": message})
        assert log.is_container_anomaly is True
        assert log.anomaly_type == expected_type


def test_cloudwatch_w3c_traceparent_and_session_extraction() -> None:
    ingestor = CloudWatchLogIngestor()
    session_id = new_uuid7()

    raw_event = {
        "logStream": "worker-2",
        "timestamp": "2026-11-15T22:30:00Z",
        "message": json.dumps(
            {
                "session_id": str(session_id),
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "message": "Step executed successfully",
            }
        ),
    }

    log = ingestor.parse_log_event(raw_event)
    assert log.session_id == session_id
    assert log.trace_id is not None
    assert log.trace_id.hex == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert log.span_id is not None
    assert log.is_container_anomaly is False


def test_otlp_span_ingestor_normalizes_openinference_format() -> None:
    ingestor = OtlpSpanIngestor()
    ctx = TenantContext(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        actor_id="otlp_client",
        role=Role.INGESTOR,
    )
    session_id = new_uuid7()

    raw_batch = [
        {
            "name": "chat_completion",
            "openinference.span.kind": "LLM",
            "llm.model_name": "claude-3-5-sonnet",
            "llm.token_count.prompt": 200,
            "llm.token_count.completion": 80,
            "cost_usd": 0.0018,
            "input.value": "Write an agent prompt",
            "output.value": "Here is the agent prompt...",
        }
    ]

    spans = ingestor.parse_span_batch(ctx, raw_batch, default_session_id=session_id)
    assert len(spans) == 1
    span = spans[0]
    assert span.span_kind == SpanKind.LLM
    assert span.operation_name == OperationName.CHAT
    assert span.model_name == "claude-3-5-sonnet"
    assert span.prompt_tokens == 200
    assert span.completion_tokens == 80
    assert span.cost_usd == pytest.approx(0.0018)


def test_phoenix_bridge_generates_valid_openinference_schema() -> None:
    bridge = ArizePhoenixBridge()
    t0 = utc_now()
    span_id = new_uuid7()
    trace_id = new_uuid7()

    span = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=new_uuid7(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=None,
        dotted_order=f"20261115T000000000000Z{str(span_id).lower()}",
        name="AgentGoalEvaluation",
        span_kind=SpanKind.AGENT,
        operation_name=OperationName.INVOKE_AGENT,
        framework=AgentFramework.LANGGRAPH,
        started_at=t0,
        model_name="gpt-4o",
        prompt_tokens=500,
        completion_tokens=120,
        cost_usd=0.006,
        input_payload={"goal": "evaluate metrics"},
        output_payload={"status": "completed"},
    )

    oi_dict = bridge.to_openinference_dict(span)
    assert oi_dict["context.span_id"] == str(span_id)
    assert oi_dict["context.trace_id"] == str(trace_id)
    assert oi_dict["span_kind"] == "AGENT"
    assert oi_dict["attributes"]["openinference.span.kind"] == "AGENT"
    assert oi_dict["attributes"]["llm.token_count.total"] == 620
    assert oi_dict["attributes"]["argus.cost_usd"] == pytest.approx(0.006)

    records = bridge.to_dataframe_records([span])
    assert len(records) == 1
    assert records[0]["name"] == "AgentGoalEvaluation"
    assert records[0]["total_tokens"] == 620
