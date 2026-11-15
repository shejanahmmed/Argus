"""Unit tests for CloudWatch log ingestion, OTLP ingestion, and Arize Phoenix bridge."""

from __future__ import annotations

import json

import pytest

from argus.core.ids import build_dotted_order, new_uuid7, utc_now
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


def test_phoenix_bridge_comprehensive_span_kinds_and_errors() -> None:
    bridge = ArizePhoenixBridge()
    t0 = utc_now()
    sess_id = new_uuid7()
    trace_id = new_uuid7()

    # 1. LLM Span
    s1_id = new_uuid7()
    llm_span = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=sess_id,
        trace_id=trace_id,
        span_id=s1_id,
        dotted_order=build_dotted_order(t0, s1_id),
        name="GenerateHypothesis",
        span_kind=SpanKind.LLM,
        operation_name=OperationName.CHAT,
        framework=AgentFramework.LANGGRAPH,
        started_at=t0,
        model_name="claude-3-5-sonnet",
        provider_name="anthropic",
        prompt_tokens=400,
        completion_tokens=150,
        cost_usd=0.00345,
        input_payload={"messages": [{"role": "user", "content": "Analyze trade"}]},
        output_payload={"content": "Here is the analysis"},
    )
    llm_dict = bridge.to_openinference_dict(llm_span)
    assert llm_dict["status_code"] == "OK"
    assert llm_dict["attributes"]["llm.model_name"] == "claude-3-5-sonnet"
    assert llm_dict["attributes"]["llm.provider"] == "anthropic"
    assert llm_dict["attributes"]["llm.token_count.total"] == 550

    # 2. Tool Span with Error
    s2_id = new_uuid7()
    tool_span = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=sess_id,
        trace_id=trace_id,
        span_id=s2_id,
        dotted_order=build_dotted_order(t0, s2_id),
        name="ExecuteSql",
        span_kind=SpanKind.TOOL,
        operation_name=OperationName.EXECUTE_TOOL,
        framework=AgentFramework.LANGGRAPH,
        started_at=t0,
        input_payload={"query": "SELECT * FROM orders"},
        output_payload={"error": "Table does not exist"},
        attributes={"tool_name": "db_query", "error": "Table does not exist"},
    )
    tool_dict = bridge.to_openinference_dict(tool_span)
    assert tool_dict["status_code"] == "ERROR"
    assert tool_dict["status_message"] == "Table does not exist"
    assert tool_dict["attributes"]["tool.name"] == "db_query"
    assert tool_dict["attributes"]["exception.message"] == "Table does not exist"

    # 3. Retriever Span
    s3_id = new_uuid7()
    retriever_span = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=sess_id,
        trace_id=trace_id,
        span_id=s3_id,
        dotted_order=build_dotted_order(t0, s3_id),
        name="FetchDocuments",
        span_kind=SpanKind.RETRIEVER,
        operation_name=OperationName.RETRIEVE,
        framework=AgentFramework.LANGGRAPH,
        started_at=t0,
        input_payload={"query": "trading policies"},
        output_payload={"documents": ["Doc 1: risk limits", "Doc 2: leverage limits"]},
    )
    retriever_dict = bridge.to_openinference_dict(retriever_span)
    assert retriever_dict["status_code"] == "OK"
    assert "retrieval.documents" in retriever_dict["attributes"]
    assert len(retriever_dict["attributes"]["retrieval.documents"]) == 2


def test_phoenix_bridge_dataframe_records_and_csv_generation() -> None:
    bridge = ArizePhoenixBridge()
    t0 = utc_now()
    sess_id = new_uuid7()
    trace_id = new_uuid7()

    s1_id = new_uuid7()
    s1 = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=sess_id,
        trace_id=trace_id,
        span_id=s1_id,
        dotted_order=build_dotted_order(t0, s1_id),
        name="AgentStep",
        span_kind=SpanKind.AGENT,
        operation_name=OperationName.INVOKE_AGENT,
        started_at=t0,
        cost_usd=0.01,
    )
    s2_id = new_uuid7()
    s2 = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=sess_id,
        trace_id=trace_id,
        span_id=s2_id,
        dotted_order=build_dotted_order(t0, s2_id),
        name="ToolStep",
        span_kind=SpanKind.TOOL,
        operation_name=OperationName.EXECUTE_TOOL,
        started_at=t0,
        cost_usd=0.002,
        attributes={"tool_name": "calculator"},
    )

    records = bridge.to_dataframe_records([s1, s2])
    assert len(records) == 2
    assert records[0]["name"] == "AgentStep"
    assert records[0]["cost_usd"] == 0.01
    assert records[1]["attributes.tool.name"] == "calculator"

    csv_data = bridge.to_dataframe_csv([s1, s2])
    assert "span_id" in csv_data
    assert "AgentStep" in csv_data
    assert "ToolStep" in csv_data
    lines = csv_data.strip().split("\r\n" if "\r\n" in csv_data else "\n")
    assert len(lines) == 3  # Header + 2 data rows


def test_phoenix_bridge_eval_datasets_extraction() -> None:
    bridge = ArizePhoenixBridge()
    t0 = utc_now()
    sess_id = new_uuid7()
    trace_id = new_uuid7()

    s1_id = new_uuid7()
    s2_id = new_uuid7()
    s3_id = new_uuid7()

    spans = [
        ArgusSpan(
            tenant_id="tenant_a",
            workspace_id="ws_1",
            session_id=sess_id,
            trace_id=trace_id,
            span_id=s1_id,
            dotted_order=build_dotted_order(t0, s1_id),
            name="RetrieveDocs",
            span_kind=SpanKind.RETRIEVER,
            operation_name=OperationName.RETRIEVE,
            started_at=t0,
            output_payload={"documents": ["Relevant context chunk"]},
        ),
        ArgusSpan(
            tenant_id="tenant_a",
            workspace_id="ws_1",
            session_id=sess_id,
            trace_id=trace_id,
            span_id=s2_id,
            dotted_order=build_dotted_order(t0, s2_id),
            name="GenerateAnswer",
            span_kind=SpanKind.LLM,
            operation_name=OperationName.CHAT,
            started_at=t0,
            model_name="gpt-4o",
            input_payload={"prompt": "What is the policy?"},
            output_payload={"response": "The policy requires 10% reserve."},
            cost_usd=0.005,
        ),
        ArgusSpan(
            tenant_id="tenant_a",
            workspace_id="ws_1",
            session_id=sess_id,
            trace_id=trace_id,
            span_id=s3_id,
            dotted_order=build_dotted_order(t0, s3_id),
            name="ExecuteAuditTool",
            span_kind=SpanKind.TOOL,
            operation_name=OperationName.EXECUTE_TOOL,
            started_at=t0,
            input_payload={"action": "log_event"},
            output_payload={"status": "success"},
            attributes={"tool_name": "auditor"},
            cost_usd=0.001,
        ),
    ]

    eval_data = bridge.generate_eval_datasets(spans)
    # 1. Hallucination dataset
    assert len(eval_data.hallucination_records) == 1
    h_rec = eval_data.hallucination_records[0]
    assert "What is the policy?" in h_rec["query"]
    assert "The policy requires 10% reserve." in h_rec["response"]
    assert "Relevant context chunk" in h_rec["context"]

    # 2. Tool dataset
    assert len(eval_data.tool_calling_records) == 1
    t_rec = eval_data.tool_calling_records[0]
    assert t_rec["tool_name"] == "auditor"
    assert t_rec["status"] == "SUCCESS"

    # 3. Trajectory dataset
    assert len(eval_data.trajectory_records) == 3
    assert eval_data.trajectory_records[0]["step_index"] == 0
    assert eval_data.trajectory_records[2]["step_index"] == 2
    assert eval_data.trajectory_records[2]["cumulative_cost_usd"] == pytest.approx(0.006)


def test_phoenix_bridge_bi_directional_translation() -> None:
    bridge = ArizePhoenixBridge()
    t0 = utc_now()
    sess_id = new_uuid7()
    trace_id = new_uuid7()
    s_id = new_uuid7()

    original_span = ArgusSpan(
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=sess_id,
        trace_id=trace_id,
        span_id=s_id,
        dotted_order=build_dotted_order(t0, s_id),
        name="AgentReasoning",
        span_kind=SpanKind.LLM,
        operation_name=OperationName.CHAT,
        started_at=t0,
        model_name="deepseek-v3",
        provider_name="deepseek",
        prompt_tokens=1000,
        completion_tokens=250,
        cost_usd=0.00035,
        input_payload={"prompt": "Calculate ratio"},
        output_payload={"result": "Ratio is 1.5"},
    )

    # 1. Convert to OpenInference dict
    oi_dict = bridge.to_openinference_dict(original_span)

    # 2. Convert back to ArgusSpan
    converted_span = bridge.from_openinference_dict(
        raw=oi_dict,
        tenant_id="tenant_a",
        workspace_id="ws_1",
        session_id=sess_id,
        trace_id=trace_id,
        dotted_order=original_span.dotted_order,
    )

    assert converted_span.span_id == original_span.span_id
    assert converted_span.span_kind == SpanKind.LLM
    assert converted_span.operation_name == OperationName.CHAT
    assert converted_span.model_name == "deepseek-v3"
    assert converted_span.provider_name == "deepseek"
    assert converted_span.prompt_tokens == 1000
    assert converted_span.completion_tokens == 250
    assert converted_span.cost_usd == pytest.approx(0.00035)
