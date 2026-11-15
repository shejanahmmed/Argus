"""Unit tests for Model Pricing, Framework Adapters, Spool Replay, and HttpTraceStore."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from argus.adapters_infra.http_store import HttpTraceStore
from argus.adapters_infra.in_memory import InMemoryTraceStore
from argus.api.app import app
from argus.api.dependencies import get_container
from argus.core.ids import new_uuid7
from argus.core.pricing import (
    estimate_token_cost_usd,
    normalize_model_name,
)
from argus.core.schemas import AgentFramework, AgentSession, ArgusSpan, OperationName, SpanKind
from argus.core.tenancy import Role, TenantContext
from argus.ingestors.otlp_receiver import OtlpSpanIngestor
from argus.sdk.adapters.autogpt import ArgusAutoGPTTracker
from argus.sdk.adapters.crewai import ArgusCrewAIAdapter
from argus.sdk.adapters.langchain import ArgusLangChainCallbackHandler
from argus.sdk.adapters.langgraph import ArgusLangGraphCallbackHandler
from argus.sdk.tracer import ArgusTracer


def test_model_pricing_normalization_and_cost_estimation() -> None:
    # 1. Normalization tests
    assert normalize_model_name("claude-3-5-sonnet-20241022") == "claude-3-5-sonnet"
    assert normalize_model_name("openai/gpt-4o") == "gpt-4o"
    assert normalize_model_name("DEEPSEEK/deepseek-v3") == "deepseek-v3"
    assert normalize_model_name(None) == "unknown"

    # 2. Exact cost calculations
    # Claude 3.5 Sonnet: $3.00 / $15.00 per 1M tokens
    # 10,000 prompt tokens = $0.03, 1,000 completion tokens = $0.015 -> total = $0.045
    cost_claude = estimate_token_cost_usd("claude-3-5-sonnet", 10_000, 1_000)
    assert abs(cost_claude - 0.045) < 1e-6

    # GPT-4o Mini: $0.15 / $0.60 per 1M tokens
    # 100,000 prompt tokens = $0.015, 10,000 completion tokens = $0.006 -> total = $0.021
    cost_mini = estimate_token_cost_usd("gpt-4o-mini", 100_000, 10_000)
    assert abs(cost_mini - 0.021) < 1e-6

    # Zero tokens returns 0.0
    assert estimate_token_cost_usd("gpt-4o", 0, 0) == 0.0

    # Unrecognized model uses fallback rate ($1.00 / $3.00)
    cost_unknown = estimate_token_cost_usd("custom-finetuned-model-x", 1_000_000, 1_000_000)
    assert abs(cost_unknown - 4.00) < 1e-6


@pytest.mark.asyncio
async def test_span_builder_auto_pricing_and_error_recording() -> None:
    store = InMemoryTraceStore()
    tracer = ArgusTracer(trace_store=store, spool_path=None)
    ctx = TenantContext(tenant_id="t1", workspace_id="w1", actor_id="a1", role=Role.ADMIN)
    session_id = new_uuid7()

    async with tracer.start_span(
        ctx,
        name="test_llm_inference",
        span_kind=SpanKind.LLM,
        operation_name=OperationName.CHAT,
        session_id=session_id,
        model_name="claude-3-5-sonnet",
    ) as builder:
        # Prompt: 10,000, Completion: 1,000 -> Expected $0.045
        builder.record_tokens(prompt_tokens=10_000, completion_tokens=1_000)
        assert abs(builder.cost_usd - 0.045) < 1e-6

        # Record error on builder
        builder.record_error("RateLimitError: 429 Too Many Requests")
        assert builder.attributes["error"] is True
        assert "RateLimitError" in str(builder.attributes["error.message"])

    spans = await store.get_session_spans(ctx, session_id)
    assert len(spans) == 1
    assert abs(spans[0].cost_usd - 0.045) < 1e-6
    assert spans[0].attributes["error"] is True


@pytest.mark.asyncio
async def test_langchain_callback_handler_full_lifecycle_and_errors() -> None:
    store = InMemoryTraceStore()
    tracer = ArgusTracer(trace_store=store, spool_path=None)
    ctx = TenantContext(tenant_id="t1", workspace_id="w1", actor_id="a1", role=Role.ADMIN)
    session_id = new_uuid7()

    handler = ArgusLangChainCallbackHandler(tracer=tracer, ctx=ctx, session_id=session_id)

    # 1. Chain start & end
    chain_run_id = uuid.uuid4()
    await handler.on_chain_start(
        {"name": "RagPipeline"},
        {"question": "How does Argus work?"},
        run_id=chain_run_id,
    )
    await handler.on_chain_end(
        {"answer": "Argus is a zero-tolerance control plane."},
        run_id=chain_run_id,
    )

    # 2. Tool start & error
    tool_run_id = uuid.uuid4()
    await handler.on_tool_start(
        {"name": "sql_query_tool"},
        "SELECT * FROM agents",
        run_id=tool_run_id,
    )
    await handler.on_tool_error(
        RuntimeError("Database connection lost"),
        run_id=tool_run_id,
    )

    # 3. LLM start & end with automated pricing
    llm_run_id = uuid.uuid4()
    await handler.on_llm_start(
        {"name": "ChatOpenAI"},
        ["Summarize this telemetry."],
        run_id=llm_run_id,
        invocation_params={"model_name": "gpt-4o-mini"},
    )
    await handler.on_llm_end(
        {"llm_output": {"token_usage": {"prompt_tokens": 1000, "completion_tokens": 500}}},
        run_id=llm_run_id,
    )

    # Verify spans in store
    spans = await store.get_session_spans(ctx, session_id)
    assert len(spans) == 3

    chain_span = next(s for s in spans if s.name == "RagPipeline")
    assert chain_span.framework == AgentFramework.LANGCHAIN
    assert chain_span.span_kind == SpanKind.CHAIN

    tool_span = next(s for s in spans if s.name == "tool:sql_query_tool")
    assert tool_span.attributes.get("error") is True
    assert "Database connection lost" in str(tool_span.attributes.get("error.message"))

    llm_span = next(s for s in spans if s.name == "chat:completion")
    assert llm_span.prompt_tokens == 1000
    assert llm_span.completion_tokens == 500
    assert llm_span.cost_usd > 0.0


@pytest.mark.asyncio
async def test_langgraph_and_crewai_and_autogpt_error_resilience() -> None:
    store = InMemoryTraceStore()
    tracer = ArgusTracer(trace_store=store, spool_path=None)
    ctx = TenantContext(tenant_id="t1", workspace_id="w1", actor_id="a1", role=Role.ADMIN)
    session_id = new_uuid7()

    # 1. LangGraph error handlers
    lg_handler = ArgusLangGraphCallbackHandler(tracer=tracer, ctx=ctx, session_id=session_id)
    lg_run = uuid.uuid4()
    await lg_handler.on_chain_start({"name": "supervisor_node"}, {"step": 1}, run_id=lg_run)
    await lg_handler.on_chain_error(ValueError("Invalid graph state transition"), run_id=lg_run)

    # 2. CrewAI error handler
    crew_adapter = ArgusCrewAIAdapter(tracer=tracer, ctx=ctx, session_id=session_id)
    await crew_adapter.on_task_start(
        task_id="task_sec_01",
        agent_role="SecOpsAuditor",
        description="Scan container images for vulnerabilities",
    )
    await crew_adapter.on_task_error(
        task_id="task_sec_01",
        error=RuntimeError("Docker daemon socket timeout"),
    )

    # 3. AutoGPT error cycle
    autogpt_tracker = ArgusAutoGPTTracker(tracer=tracer, ctx=ctx, session_id=session_id)
    with pytest.raises(ZeroDivisionError):
        async with autogpt_tracker.track_cycle(1, thought="Calculate ratio"):
            _ = 1 / 0

    spans = await store.get_session_spans(ctx, session_id)
    assert len(spans) == 3

    lg_span = next(s for s in spans if s.name == "supervisor_node")
    assert lg_span.attributes.get("error") is True

    crew_span = next(s for s in spans if "crewai" in s.name)
    assert crew_span.attributes.get("error") is True

    autogpt_span = next(s for s in spans if "autogpt" in s.name)
    assert autogpt_span.attributes.get("error") is True


@pytest.mark.asyncio
async def test_fail_open_spool_and_flush_replay(tmp_path: Path) -> None:
    spool_file = tmp_path / "spool_spans.jsonl"
    ctx = TenantContext(tenant_id="t_spool", workspace_id="w_spool", actor_id="a1", role=Role.ADMIN)
    session_id = new_uuid7()

    class BrokenStore:
        async def append_spans(self, ctx: TenantContext, spans: list[ArgusSpan]) -> int:
            raise ConnectionError("Mock network partition to Argus Control Plane")

    broken_tracer = ArgusTracer(
        trace_store=BrokenStore(),  # type: ignore[arg-type]
        spool_path=spool_file,
    )

    # 1. Tracing when storage is down must NOT crash (fail-open)
    async with broken_tracer.start_span(
        ctx,
        name="offline_span",
        span_kind=SpanKind.AGENT,
        operation_name=OperationName.INVOKE_AGENT,
        session_id=session_id,
        input_payload={"status": "spooled_offline"},
    ) as builder:
        builder.set_output({"res": "ok"})

    assert spool_file.exists()
    spool_lines = spool_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(spool_lines) == 1
    assert "offline_span" in spool_lines[0]

    # 2. Connectivity restored: flush spool to healthy store
    healthy_store = InMemoryTraceStore()
    recovered_tracer = ArgusTracer(trace_store=healthy_store, spool_path=spool_file)

    flushed = await recovered_tracer.flush_spool(ctx)
    assert flushed == 1

    # Spool file must be unlinked or empty
    assert not spool_file.exists() or spool_file.read_text(encoding="utf-8").strip() == ""

    # Healthy store contains the replayed span
    spans = await healthy_store.get_session_spans(ctx, session_id)
    assert len(spans) == 1
    assert spans[0].name == "offline_span"


@pytest.mark.asyncio
async def test_http_trace_store_and_remote_tracer() -> None:
    container = get_container()
    ctx = TenantContext(
        tenant_id="t_http", workspace_id="w_http", actor_id="a_http", role=Role.ADMIN
    )
    token = container.authenticator.issue_token(ctx)
    session_id = new_uuid7()

    # Pre-create session so span ingestion links properly
    await container.control_store.create_session(
        ctx,
        AgentSession(
            session_id=session_id,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            workflow_id="wf_http",
            agent_name="agent_http",
            framework=AgentFramework.CUSTOM,
            budget_cap_usd=50.0,
        ),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        http_store = HttpTraceStore(
            base_url="http://testserver",
            auth_token=token,
            client=test_client,
        )
        remote_tracer = ArgusTracer(trace_store=http_store, spool_path=None)

        # Trace remotely over HTTP
        async with remote_tracer.start_span(
            ctx,
            name="remote_http_span",
            span_kind=SpanKind.TOOL,
            operation_name=OperationName.EXECUTE_TOOL,
            session_id=session_id,
            input_payload={"cmd": "ls -la"},
        ) as builder:
            builder.set_output({"stdout": "total 0"})

        # Query session spans back over HTTP
        retrieved_spans = await http_store.get_session_spans(ctx, session_id)
        assert len(retrieved_spans) >= 1
        assert any(s.name == "remote_http_span" for s in retrieved_spans)


def test_otlp_ingress_pii_scrubbing_and_cost() -> None:
    ctx = TenantContext(tenant_id="t_otlp", workspace_id="w_otlp", actor_id="a1", role=Role.ADMIN)
    session_id = new_uuid7()
    ingestor = OtlpSpanIngestor()

    raw_spans = [
        {
            "name": "chat_with_leaked_key",
            "openinference.span.kind": "LLM",
            "llm.model_name": "gpt-4o",
            "llm.token_count.prompt": 2000,
            "llm.token_count.completion": 1000,
            "input_payload": {
                "system": "Use this key sk-proj-123456789012345678 to query billing",
                "ssn": "123-45-6789",
            },
            "output_payload": {"text": "I will proceed with the billing request."},
        }
    ]

    parsed = ingestor.parse_span_batch(ctx, raw_spans, default_session_id=session_id)
    assert len(parsed) == 1
    span = parsed[0]

    # Check PII scrubbing
    assert "[REDACTED_API_KEY]" in str(span.input_payload["system"])
    assert "sk-proj" not in str(span.input_payload["system"])
    assert span.input_payload["ssn"] == "[REDACTED_BY_ARGUS]"
    assert span.redacted is True

    # Check automatic cost calculation: 2,000 p_tok ($0.005) + 1,000 c_tok ($0.010) = $0.015
    assert abs(span.cost_usd - 0.015) < 1e-5
