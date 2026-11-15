"""Deterministic zero-spend multi-agent scenario seeder for C2 console evaluation."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.api.routes.telemetry import (
    IngestSpansRequest,
    ingest_cloudwatch,
    ingest_spans,
)
from argus.core.ids import build_dotted_order, new_uuid7, utc_now
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    ArgusSpan,
    CheckpointRecord,
    CloudWatchIngestRequest,
    OperationName,
    PendingToolCall,
    SessionStatus,
    SpanKind,
)
from argus.core.tenancy import TenantContext

router = APIRouter(prefix="/api/v1/demo", tags=["Demo & Simulation"])


@router.post("/seed", response_model=dict[str, Any])
async def seed_demo_scenario(
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> dict[str, Any]:
    """Seed a realistic multi-agent fleet scenario with loops, C2 intercepts, and logs."""
    base_time = utc_now() - timedelta(minutes=2)

    # 1. Session 1: LangGraph Research Agent that trips Tier-1 Loop Breaker
    s1_id = new_uuid7()
    s1 = AgentSession(
        session_id=s1_id,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        workflow_id="wf_order_reconciliation",
        agent_name="langgraph-order-reconciler",
        framework=AgentFramework.LANGGRAPH,
        budget_cap_usd=25.0,
    )
    await container.control_store.create_session(ctx, s1)

    t1_id = new_uuid7()
    s1_root_id = new_uuid7()
    s1_root_time = base_time
    s1_root_do = build_dotted_order(s1_root_time, s1_root_id)
    s1_spans: list[ArgusSpan] = [
        ArgusSpan(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=s1_id,
            trace_id=t1_id,
            span_id=s1_root_id,
            parent_span_id=None,
            dotted_order=s1_root_do,
            name="langgraph:supervisor_node",
            span_kind=SpanKind.AGENT,
            operation_name=OperationName.INVOKE_AGENT,
            framework=AgentFramework.LANGGRAPH,
            model_name="claude-3-5-sonnet",
            prompt_tokens=920,
            completion_tokens=240,
            cost_usd=0.00636,
            latency_ms=410.0,
            input_payload={"goal": "Reconcile stalled settlement batch #849"},
            output_payload={"thought": "Dispatching SQL query to inspect pending orders."},
            started_at=s1_root_time,
        )
    ]

    for idx in range(3):
        step_id = new_uuid7()
        step_time = s1_root_time + timedelta(seconds=(idx + 1) * 2)
        s1_spans.append(
            ArgusSpan(
                tenant_id=ctx.tenant_id,
                workspace_id=ctx.workspace_id,
                session_id=s1_id,
                trace_id=t1_id,
                span_id=step_id,
                parent_span_id=s1_root_id,
                dotted_order=build_dotted_order(step_time, step_id, s1_root_do),
                name="query_settlement_ledger",
                span_kind=SpanKind.TOOL,
                operation_name=OperationName.EXECUTE_TOOL,
                framework=AgentFramework.LANGGRAPH,
                model_name="claude-3-5-sonnet",
                prompt_tokens=600,
                completion_tokens=150,
                cost_usd=0.00405,
                latency_ms=285.0,
                input_payload={"sql": "SELECT * FROM settlements WHERE batch_id = 849"},
                output_payload={"rows": [], "status": "LOCK_WAIT_TIMEOUT"},
                attributes={
                    "tool_name": "query_settlement_ledger",
                    **({"circuit_breaker_flag": "EXACT_TOOL_LOOP"} if idx >= 1 else {}),
                },
                started_at=step_time,
            )
        )

    await ingest_spans(IngestSpansRequest(spans=s1_spans), ctx=ctx, container=container)

    cp1 = CheckpointRecord(
        checkpoint_id=new_uuid7(),
        parent_checkpoint_id=None,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=s1_id,
        node_name="query_settlement_ledger",
        step_index=3,
        memory_state={
            "plan": ["query_settlement_ledger", "backoff_and_switch_replica", "verify_ledger"],
            "retry_count": 3,
            "use_read_replica": False,
        },
        created_at=utc_now(),
    )
    await container.control_store.save_checkpoint(ctx, cp1, expected_parent_id=None)
    await container.audit_store.append_event(
        ctx,
        session_id=s1_id,
        event_type="CIRCUIT_BREAKER_TRIPPED",
        payload={"reason": "EXACT_TOOL_LOOP", "tool_name": "query_settlement_ledger"},
    )

    # 2. Session 2: CrewAI SecOps Executor paused on destructive MCP tool call
    s2_id = new_uuid7()
    s2 = AgentSession(
        session_id=s2_id,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        workflow_id="wf_db_maintenance",
        agent_name="crewai-secops-remediator",
        framework=AgentFramework.CREWAI,
        budget_cap_usd=50.0,
    )
    await container.control_store.create_session(ctx, s2)

    t2_id = new_uuid7()
    s2_root_id = new_uuid7()
    s2_root_time = base_time + timedelta(seconds=15)
    s2_root_do = build_dotted_order(s2_root_time, s2_root_id)
    s2_llm_id = new_uuid7()
    s2_llm_time = s2_root_time + timedelta(seconds=2)

    s2_spans: list[ArgusSpan] = [
        ArgusSpan(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=s2_id,
            trace_id=t2_id,
            span_id=s2_root_id,
            parent_span_id=None,
            dotted_order=s2_root_do,
            name="crewai:secops_task",
            span_kind=SpanKind.AGENT,
            operation_name=OperationName.INVOKE_AGENT,
            framework=AgentFramework.CREWAI,
            cost_usd=0.002,
            latency_ms=190.0,
            input_payload={"task": "Purge stale staging tables"},
            output_payload={"content": "Evaluating candidate tables for cleanup."},
            started_at=s2_root_time,
        ),
        ArgusSpan(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=s2_id,
            trace_id=t2_id,
            span_id=s2_llm_id,
            parent_span_id=s2_root_id,
            dotted_order=build_dotted_order(s2_llm_time, s2_llm_id, s2_root_do),
            name="llm:claude-3-5-sonnet",
            span_kind=SpanKind.LLM,
            operation_name=OperationName.CHAT,
            framework=AgentFramework.CREWAI,
            model_name="claude-3-5-sonnet",
            prompt_tokens=1420,
            completion_tokens=380,
            cost_usd=0.00996,
            latency_ms=640.0,
            input_payload={"messages": ["Identify tables to drop"]},
            output_payload={"content": "Calling drop_production_table on customer_audit_archive."},
            started_at=s2_llm_time,
        ),
    ]
    await ingest_spans(IngestSpansRequest(spans=s2_spans), ctx=ctx, container=container)

    pending_call = PendingToolCall(
        tool_call_id="mcp_call_901",
        tool_name="drop_production_table",
        tool_args={"table": "customer_audit_archive", "cascade": True, "env": "prod"},
        is_destructive=True,
    )
    container.pending_tool_calls.setdefault(f"{ctx.tenant_id}:{s2_id}", []).append(pending_call)
    await container.control_store.transition_session(
        ctx,
        session_id=s2_id,
        expected_status=SessionStatus.RUNNING,
        next_status=SessionStatus.PAUSED_C2,
    )

    cp2 = CheckpointRecord(
        checkpoint_id=new_uuid7(),
        parent_checkpoint_id=None,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=s2_id,
        node_name="mcp_tool_gate",
        step_index=2,
        memory_state={
            "plan": ["inspect_schema", "drop_production_table", "vacuum_analyze"],
            "target_env": "prod",
            "require_human_signoff": True,
        },
        pending_tool_call=pending_call,
        created_at=utc_now(),
    )
    await container.control_store.save_checkpoint(ctx, cp2, expected_parent_id=None)
    await container.audit_store.append_event(
        ctx,
        session_id=s2_id,
        event_type="MCP_DESTRUCTIVE_TOOL_INTERCEPTED",
        payload={
            "tool_call_id": pending_call.tool_call_id,
            "tool_name": pending_call.tool_name,
            "request_digest_sha256": pending_call.request_digest_sha256,
        },
    )

    # 3. Session 3: AutoGPT FinOps Synthesizer (RUNNING)
    s3_id = new_uuid7()
    s3 = AgentSession(
        session_id=s3_id,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        workflow_id="wf_finops_audit",
        agent_name="autogpt-finops-synthesizer",
        framework=AgentFramework.AUTOGPT,
        budget_cap_usd=40.0,
    )
    await container.control_store.create_session(ctx, s3)

    t3_id = new_uuid7()
    s3_root_id = new_uuid7()
    s3_root_time = base_time + timedelta(seconds=30)
    s3_root_do = build_dotted_order(s3_root_time, s3_root_id)
    s3_spans = [
        ArgusSpan(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=s3_id,
            trace_id=t3_id,
            span_id=s3_root_id,
            parent_span_id=None,
            dotted_order=s3_root_do,
            name="autogpt:finops_cycle",
            span_kind=SpanKind.LLM,
            operation_name=OperationName.CHAT,
            framework=AgentFramework.AUTOGPT,
            model_name="deepseek-v3",
            prompt_tokens=1100,
            completion_tokens=450,
            cost_usd=0.0028,
            latency_ms=310.0,
            input_payload={"objective": "Compute Q4 Pareto efficiency report"},
            output_payload={"content": "Completed FinOps model utilization synthesis."},
            started_at=s3_root_time,
        )
    ]
    await ingest_spans(IngestSpansRequest(spans=s3_spans), ctx=ctx, container=container)

    # 4. Ingest Correlated CloudWatch Container Logs
    cw_events = [
        {
            "logGroup": "/aws/ecs/argus-agent-workers",
            "logStream": "worker-langgraph-01",
            "severity": "INFO",
            "message": (
                f'{{"trace_id": "{t1_id}", "span_id": "{s1_root_id}", '
                '"level": "INFO", "msg": "LangGraph supervisor checkpoint committed."}'
            ),
        },
        {
            "logGroup": "/aws/ecs/argus-agent-workers",
            "logStream": "worker-langgraph-01",
            "severity": "ERROR",
            "message": (
                f'{{"trace_id": "{t1_id}", "level": "ERROR", '
                '"msg": "Container memory pressure warning: OOMKilled exit code 137 on replica-2"}'
            ),
        },
        {
            "logGroup": "/aws/ecs/argus-agent-workers",
            "logStream": "worker-crewai-secops",
            "severity": "WARN",
            "message": (
                f'{{"trace_id": "{t2_id}", "span_id": "{s2_llm_id}", '
                '"level": "WARN", '
                '"msg": "MCP Proxy paused destructive tool call drop_production_table."}'
            ),
        },
    ]
    await ingest_cloudwatch(
        CloudWatchIngestRequest(log_events=cw_events),
        ctx=ctx,
        container=container,
    )

    return {
        "status": "seeded",
        "sessions_created": [str(s1_id), str(s2_id), str(s3_id)],
        "tripped_session_id": str(s1_id),
        "paused_c2_session_id": str(s2_id),
        "running_session_id": str(s3_id),
    }
