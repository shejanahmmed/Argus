"""Comprehensive integration tests for Argus Control Plane FastAPI endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from argus.api.app import app
from argus.api.dependencies import get_container
from argus.core.ids import build_dotted_order, new_uuid7, utc_now
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    ArgusSpan,
    CheckpointRecord,
    OperationName,
    PendingToolCall,
    SessionStatus,
    SpanKind,
)
from argus.core.tenancy import Role, TenantContext


@pytest.fixture(autouse=True)
def reset_app_state() -> None:
    """Ensure clean container state before each test."""
    get_container().reset()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {
        "X-Tenant-ID": "test_tenant",
        "X-Workspace-ID": "test_workspace",
        "X-Actor-ID": "admin_user",
        "X-Role": "ADMIN",
    }


@pytest.mark.asyncio
async def test_health_and_root_endpoints() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        res_health = await client.get("/healthz")
        assert res_health.status_code == 200
        assert res_health.json()["status"] == "HEALTHY"

        res_root = await client.get("/")
        assert res_root.status_code == 200
        assert "docs_url" in res_root.json()


@pytest.mark.asyncio
async def test_telemetry_span_ingestion_and_query(auth_headers: dict[str, str]) -> None:
    container = get_container()
    ctx = TenantContext(
        tenant_id="test_tenant",
        workspace_id="test_workspace",
        actor_id="admin_user",
        role=Role.ADMIN,
    )
    session_id = new_uuid7()
    session = AgentSession(
        session_id=session_id,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        workflow_id="wf_alpha",
        agent_name="researcher",
        framework=AgentFramework.LANGGRAPH,
        budget_cap_usd=50.0,
    )
    await container.control_store.create_session(ctx, session)

    trace_id = new_uuid7()
    span1_id = new_uuid7()
    now = utc_now()
    span1 = ArgusSpan(
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=span1_id,
        parent_span_id=None,
        dotted_order=build_dotted_order(now, span1_id),
        name="agent_step_1",
        span_kind=SpanKind.AGENT,
        operation_name=OperationName.INVOKE_AGENT,
        cost_usd=0.005,
        output_payload={"content": "Initial step executing."},
        started_at=now,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Ingest span
        resp = await client.post(
            "/api/v1/telemetry/spans",
            headers=auth_headers,
            json={"spans": [span1.model_dump(mode="json")]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingested_count"] == 1
        assert data["tripped_circuit_breaker"] is False

        # Query session spans
        spans_resp = await client.get(
            f"/api/v1/telemetry/sessions/{session_id}/spans",
            headers=auth_headers,
        )
        assert spans_resp.status_code == 200
        session_spans = spans_resp.json()
        assert len(session_spans) == 1
        assert session_spans[0]["name"] == "agent_step_1"

        # List sessions
        sessions_resp = await client.get("/api/v1/telemetry/sessions", headers=auth_headers)
        assert sessions_resp.status_code == 200
        sessions_list = sessions_resp.json()
        assert len(sessions_list) == 1
        assert sessions_list[0]["session_id"] == str(session_id)


@pytest.mark.asyncio
async def test_loop_detection_tripping_in_telemetry(auth_headers: dict[str, str]) -> None:
    container = get_container()
    ctx = TenantContext(
        tenant_id="test_tenant",
        workspace_id="test_workspace",
        actor_id="admin_user",
        role=Role.ADMIN,
    )
    session_id = new_uuid7()
    session = AgentSession(
        session_id=session_id,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        workflow_id="wf_alpha",
        agent_name="researcher",
        framework=AgentFramework.LANGGRAPH,
        budget_cap_usd=50.0,
    )
    await container.control_store.create_session(ctx, session)

    trace_id = new_uuid7()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Ingest identical tool call three times to trigger Tier 1 loop detector
        for i in range(3):
            span_id = new_uuid7()
            now = utc_now()
            span = ArgusSpan(
                tenant_id=ctx.tenant_id,
                workspace_id=ctx.workspace_id,
                session_id=session_id,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                dotted_order=build_dotted_order(now, span_id),
                name=f"tool_step_{i}",
                span_kind=SpanKind.TOOL,
                operation_name=OperationName.EXECUTE_TOOL,
                attributes={"tool_name": "query_database"},
                input_payload={"sql": "SELECT 1"},
                started_at=now,
            )
            resp = await client.post(
                "/api/v1/telemetry/spans",
                headers=auth_headers,
                json={"spans": [span.model_dump(mode="json")]},
            )
            assert resp.status_code == 200
            data = resp.json()
            if i == 2:
                # Third identical call trips Tier 1 exact match
                assert data["tripped_circuit_breaker"] is True
                assert "Tier 1" in (data["warning"] or "")

        # Session should be transitioned to TRIPPED_LOOP
        updated_session = await container.control_store.get_session(ctx, session_id)
        assert updated_session.status == SessionStatus.TRIPPED_LOOP


@pytest.mark.asyncio
async def test_cloudwatch_log_ingestion(auth_headers: dict[str, str]) -> None:
    trace_id = uuid.uuid4()
    events = [
        {
            "logGroup": "/aws/ecs/agent-cluster",
            "logStream": "worker-1",
            "message": f'{{"trace_id": "{trace_id}", "msg": "Worker processing step."}}',
        },
        {
            "logGroup": "/aws/ecs/agent-cluster",
            "logStream": "worker-1",
            "message": "Out of memory fatal crash: OOMKilled exit code 137",
        },
    ]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/api/v1/telemetry/cloudwatch",
            headers=auth_headers,
            json={"log_events": events},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_logs"] == 2
        assert data["anomalies_count"] == 1
        assert data["correlated_trace_count"] == 1


@pytest.mark.asyncio
async def test_c2_state_patch_and_concurrency(auth_headers: dict[str, str]) -> None:
    container = get_container()
    ctx = TenantContext(
        tenant_id="test_tenant",
        workspace_id="test_workspace",
        actor_id="admin_user",
        role=Role.ADMIN,
    )
    session_id = new_uuid7()
    session = AgentSession(
        session_id=session_id,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        workflow_id="wf_beta",
        agent_name="executor",
        framework=AgentFramework.CREWAI,
        budget_cap_usd=25.0,
    )
    await container.control_store.create_session(ctx, session)

    # Create root checkpoint
    cp_id = new_uuid7()
    root_cp = CheckpointRecord(
        checkpoint_id=cp_id,
        parent_checkpoint_id=None,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        node_name="entrypoint",
        step_index=0,
        memory_state={"counter": 1, "status": "init"},
        created_at=utc_now(),
    )
    await container.control_store.save_checkpoint(ctx, root_cp, expected_parent_id=None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. Pause session
        pause_resp = await client.post(
            f"/api/v1/c2/{session_id}/pause",
            headers=auth_headers,
            json={"operator_id": "op_99", "reason": "Operator inspecting state"},
        )
        assert pause_resp.status_code == 200
        assert pause_resp.json()["status"] == SessionStatus.PAUSED_C2.value

        # 2. Apply RFC 6902 JSON patch with matching expected checkpoint
        patch_payload = {
            "operator_id": "op_99",
            "expected_parent_checkpoint_id": str(cp_id),
            "patches": [
                {"op": "replace", "path": "/counter", "value": 10},
                {"op": "add", "path": "/patched", "value": True},
            ],
            "reason": "Correct counter state",
        }
        patch_resp = await client.post(
            f"/api/v1/c2/{session_id}/patch",
            headers=auth_headers,
            json=patch_payload,
        )
        assert patch_resp.status_code == 200
        new_cp_data = patch_resp.json()
        assert new_cp_data["memory_state"]["counter"] == 10
        assert new_cp_data["memory_state"]["patched"] is True

        # 3. Apply stale patch with old checkpoint ID -> expect 409 CONFLICT
        stale_resp = await client.post(
            f"/api/v1/c2/{session_id}/patch",
            headers=auth_headers,
            json=patch_payload,  # still points to cp_id instead of new_cp_id
        )
        assert stale_resp.status_code == 409
        assert "Checkpoint concurrency conflict" in stale_resp.json()["detail"]

        # 4. Resume session
        resume_resp = await client.post(
            f"/api/v1/c2/{session_id}/resume",
            headers=auth_headers,
            json={"operator_id": "op_99", "reason": "State edited successfully"},
        )
        assert resume_resp.status_code == 200
        assert resume_resp.json()["status"] == SessionStatus.RUNNING.value


@pytest.mark.asyncio
async def test_c2_tool_override_cycle(auth_headers: dict[str, str]) -> None:
    session_id = new_uuid7()
    call = PendingToolCall(
        tool_call_id="call_x1",
        tool_name="drop_table",
        tool_args={"table": "users", "force": True},
        is_destructive=True,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Register pending tool call
        reg_resp = await client.post(
            f"/api/v1/c2/{session_id}/pending-tools",
            headers=auth_headers,
            json=call.model_dump(mode="json"),
        )
        assert reg_resp.status_code == 200

        # Query pending tools
        list_resp = await client.get(
            f"/api/v1/c2/{session_id}/pending-tools",
            headers=auth_headers,
        )
        assert list_resp.status_code == 200
        pending = list_resp.json()
        assert len(pending) == 1
        assert pending[0]["tool_name"] == "drop_table"

        # Operator edits tool call args
        override_resp = await client.post(
            f"/api/v1/c2/{session_id}/tool-override",
            headers=auth_headers,
            json={
                "tool_call_id": "call_x1",
                "decision": "edit",
                "modified_args": {"table": "test_sandbox", "force": False},
                "operator_id": "op_admin",
                "reason": "Redirect destructive drop away from production",
            },
        )
        assert override_resp.status_code == 200
        res = override_resp.json()
        assert res["decision"] == "edit"
        assert res["should_execute"] is True
        assert res["effective_payload"]["table"] == "test_sandbox"

        # Queue should now be empty
        empty_resp = await client.get(
            f"/api/v1/c2/{session_id}/pending-tools",
            headers=auth_headers,
        )
        assert len(empty_resp.json()) == 0


@pytest.mark.asyncio
async def test_attribution_and_benchmarks(auth_headers: dict[str, str]) -> None:
    container = get_container()
    ctx = TenantContext(
        tenant_id="test_tenant",
        workspace_id="test_workspace",
        actor_id="admin_user",
        role=Role.ADMIN,
    )
    session_id = new_uuid7()
    trace_id = new_uuid7()
    span1_id = new_uuid7()
    now = utc_now()
    span = ArgusSpan(
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=span1_id,
        parent_span_id=None,
        dotted_order=build_dotted_order(now, span1_id),
        name="llm_call",
        span_kind=SpanKind.LLM,
        operation_name=OperationName.CHAT,
        cost_usd=0.015,
        started_at=now,
    )
    await container.trace_store.append_spans(ctx, [span])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Check ROI endpoint
        roi_resp = await client.get(
            f"/api/v1/attribution/roi/{session_id}?assigned_business_value_usd=100.0",
            headers=auth_headers,
        )
        assert roi_resp.status_code == 200
        roi_data = roi_resp.json()
        assert roi_data["total_cost_usd"] > 0.0
        assert roi_data["net_roi_usd"] > 0.0

        # Check benchmark catalog
        cat_resp = await client.get("/api/v1/attribution/benchmarks/catalog")
        assert cat_resp.status_code == 200
        assert len(cat_resp.json()) >= 3

        # Check Pareto recommendations
        rec_resp = await client.post(
            "/api/v1/attribution/benchmarks/recommend",
            json={"current_model": "claude-3-5-sonnet", "min_acceptable_accuracy": 0.50},
        )
        assert rec_resp.status_code == 200
        recs = rec_resp.json()
        assert len(recs) > 0
        assert "cost_savings_pct" in recs[0]
