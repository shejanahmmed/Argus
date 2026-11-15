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
from argus.sdk.c2_client import ArgusC2Client


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

        res_ready = await client.get("/readyz")
        assert res_ready.status_code == 200
        assert res_ready.json()["status"] == "READY"

        res_metrics = await client.get("/metrics")
        assert res_metrics.status_code == 200
        assert "argus_sessions_total" in res_metrics.text


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

        # Query resolved tool override record
        resolved_resp = await client.get(
            f"/api/v1/c2/{session_id}/tool-override/call_x1",
            headers=auth_headers,
        )
        assert resolved_resp.status_code == 200
        resolved_data = resolved_resp.json()
        assert resolved_data["tool_name"] == "drop_table"
        assert resolved_data["decision"] == "edit"
        assert resolved_data["should_execute"] is True
        assert resolved_data["effective_payload"]["table"] == "test_sandbox"
        assert resolved_data["operator_id"] == "op_admin"

        # 4. Test auto-resumption when session is PAUSED_C2
        sess_auto_id = new_uuid7()
        sess_auto = AgentSession(
            session_id=sess_auto_id,
            tenant_id="test_tenant",
            workspace_id="test_workspace",
            workflow_id="wf_auto",
            agent_name="auto_agent",
            framework=AgentFramework.LANGGRAPH,
            budget_cap_usd=10.0,
            status=SessionStatus.PAUSED_C2,
        )
        auto_ctx = TenantContext(
            tenant_id="test_tenant",
            workspace_id="test_workspace",
            actor_id="admin_user",
            role=Role.ADMIN,
        )
        await get_container().control_store.create_session(auto_ctx, sess_auto)

        call_auto = PendingToolCall(
            tool_call_id="call_auto_99",
            tool_name="purge_cache",
            tool_args={"all": True},
            is_destructive=True,
        )
        await client.post(
            f"/api/v1/c2/{sess_auto_id}/pending-tools",
            headers=auth_headers,
            json=call_auto.model_dump(mode="json"),
        )

        # Submit approve with auto_resume=True
        auto_resp = await client.post(
            f"/api/v1/c2/{sess_auto_id}/tool-override",
            headers=auth_headers,
            json={
                "tool_call_id": "call_auto_99",
                "decision": "approve",
                "operator_id": "op_admin",
                "reason": "Approve and auto-resume",
                "auto_resume": True,
            },
        )
        assert auto_resp.status_code == 200
        assert auto_resp.json()["auto_resumed"] is True

        # Verify session is now RUNNING in control store
        updated_auto_sess = await get_container().control_store.get_session(
            auto_ctx, sess_auto_id
        )
        assert updated_auto_sess.status == SessionStatus.RUNNING

        # 5. Test rejection of security exploits in modified_args
        call_exploit = PendingToolCall(
            tool_call_id="call_exploit_99",
            tool_name="exec_task",
            tool_args={"cmd": "ls"},
            is_destructive=True,
        )
        await client.post(
            f"/api/v1/c2/{session_id}/pending-tools",
            headers=auth_headers,
            json=call_exploit.model_dump(mode="json"),
        )
        bad_edit_resp = await client.post(
            f"/api/v1/c2/{session_id}/tool-override",
            headers=auth_headers,
            json={
                "tool_call_id": "call_exploit_99",
                "decision": "edit",
                "modified_args": {"cmd": "ls; rm -rf /"},
                "operator_id": "op_admin",
                "reason": "Accidental injection",
            },
        )
        assert bad_edit_resp.status_code == 400
        assert "security threat" in bad_edit_resp.json()["detail"].lower()


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


@pytest.mark.asyncio
async def test_mcp_proxy_interception_and_phoenix_export(auth_headers: dict[str, str]) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. Create session via REST API
        create_resp = await client.post(
            "/api/v1/telemetry/sessions",
            headers=auth_headers,
            json={
                "workflow_id": "wf_mcp_test",
                "agent_name": "mcp_guard_agent",
                "framework": "langgraph",
                "budget_cap_usd": 20.0,
            },
        )
        assert create_resp.status_code == 200
        session_id = create_resp.json()["session_id"]

        # 2. Filter MCP tools list by RBAC policy
        tools_resp = await client.post(
            "/api/v1/governance/mcp/tools-list",
            headers=auth_headers,
            json={
                "available_tools": [
                    {
                        "name": "safe_search",
                        "description": "Search internal documentation.",
                        "allowed_roles": ["ADMIN", "OPERATOR"],
                    }
                ]
            },
        )
        assert tools_resp.status_code == 200
        sanitized_tools = tools_resp.json()
        assert len(sanitized_tools) == 1
        assert sanitized_tools[0]["name"] == "safe_search"

        # 3. Intercept destructive MCP tool call -> pauses session and queues PendingToolCall
        intercept_resp = await client.post(
            "/api/v1/governance/mcp/intercept",
            headers=auth_headers,
            json={
                "session_id": session_id,
                "tool_call_id": "call_999",
                "tool_name": "delete_production_cluster",
                "tool_args": {"cluster": "prod-us-east-1"},
            },
        )
        assert intercept_resp.status_code == 200
        data = intercept_resp.json()
        assert data["verdict"]["recommended_action"] == "PAUSE_FOR_C2"
        assert data["pending_tool_call"]["tool_call_id"] == "call_999"

        # Verify session is paused and pending tool is queued
        pending_resp = await client.get(
            f"/api/v1/c2/{session_id}/pending-tools",
            headers=auth_headers,
        )
        assert len(pending_resp.json()) == 1

        # Create a checkpoint and trigger an operator pause/resume to populate audit log
        await client.post(
            f"/api/v1/c2/{session_id}/resume",
            headers=auth_headers,
            json={"operator_id": "admin_user", "reason": "Reviewed and cleared"},
        )

        # Verify audit log hash chain integrity
        audit_resp = await client.get(
            f"/api/v1/c2/{session_id}/audit-log",
            headers=auth_headers,
        )
        assert audit_resp.status_code == 200
        assert audit_resp.json()["chain_verified"] is True
        assert len(audit_resp.json()["entries"]) >= 1


@pytest.mark.asyncio
async def test_demo_seeder_and_phoenix_export(auth_headers: dict[str, str]) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        seed_resp = await client.post("/api/v1/demo/seed", headers=auth_headers)
        assert seed_resp.status_code == 200
        seed_data = seed_resp.json()
        assert seed_data["status"] == "seeded"
        assert len(seed_data["sessions_created"]) == 3

        first_session_id = seed_data["sessions_created"][0]

        # Export session spans in Arize Phoenix OpenInference format
        phoenix_resp = await client.get(
            f"/api/v1/telemetry/sessions/{first_session_id}/phoenix",
            headers=auth_headers,
        )
        assert phoenix_resp.status_code == 200
        phoenix_data = phoenix_resp.json()
        assert phoenix_data["span_count"] >= 3
        assert "openinference.span.kind" in phoenix_data["openinference_spans"][0]["attributes"]

        # Retrieve CloudWatch logs ring buffer
        cw_resp = await client.get("/api/v1/telemetry/cloudwatch", headers=auth_headers)
        assert cw_resp.status_code == 200
        assert len(cw_resp.json()) >= 2


@pytest.mark.asyncio
async def test_argus_c2_sdk_client(auth_headers: dict[str, str]) -> None:
    ctx = TenantContext(
        tenant_id=auth_headers["X-Tenant-ID"],
        workspace_id=auth_headers["X-Workspace-ID"],
        actor_id=auth_headers["X-Actor-ID"],
        role=Role.ADMIN,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http_client:
        sdk = ArgusC2Client(
            ctx,
            base_url="http://testserver",
            client=http_client,
        )
        session = await sdk.register_session(
            workflow_id="sdk_workflow",
            agent_name="sdk_agent",
            framework=AgentFramework.LANGGRAPH,
            budget_cap_usd=15.0,
        )
        session_id = session.session_id

        cp1 = await sdk.save_checkpoint(
            session_id=session_id,
            node_name="step_1",
            step_index=0,
            memory_state={"step": 1},
            expected_parent_checkpoint_id=None,
        )
        assert cp1.node_name == "step_1"

        latest = await sdk.get_latest_checkpoint(session_id)
        assert latest is not None
        assert latest.checkpoint_id == cp1.checkpoint_id

        verdict, pending = await sdk.intercept_tool_call(
            session_id=session_id,
            tool_call_id="sdk_tool_1",
            tool_name="drop_database",
            tool_args={"db": "analytics"},
        )
        assert verdict.recommended_action.value == "PAUSE_FOR_C2"
        assert pending is not None
        assert pending.tool_call_id == "sdk_tool_1"

        hb = await sdk.heartbeat(
            session_id=session_id,
            worker_id="sdk_worker_pod_1",
            ttl_seconds=120.0,
        )
        assert hb.directive == "PAUSE_FOR_C2"
        assert hb.worker_id == "sdk_worker_pod_1"


@pytest.mark.asyncio
async def test_bearer_token_and_w3c_baggage_auth_and_lease_reap() -> None:
    container = get_container()
    ctx = TenantContext(
        tenant_id="bearer_tenant",
        workspace_id="bearer_ws",
        actor_id="bearer_admin",
        role=Role.ADMIN,
    )
    token = container.authenticator.issue_token(ctx, ttl_seconds=300)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. Authenticate using HMAC Bearer token
        create_resp = await client.post(
            "/api/v1/telemetry/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "workflow_id": "wf_bearer",
                "agent_name": "bearer_agent",
                "framework": "langgraph",
                "budget_cap_usd": 30.0,
            },
        )
        assert create_resp.status_code == 200
        session_id = create_resp.json()["session_id"]

        # 2. Authenticate using W3C OpenTelemetry baggage header
        baggage_header = (
            "argus.tenant_id=bearer_tenant,argus.workspace_id=bearer_ws,"
            "argus.actor_id=baggage_op,argus.role=OPERATOR"
        )
        list_resp = await client.get(
            "/api/v1/telemetry/sessions",
            headers={"baggage": baggage_header},
        )
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        assert list_resp.json()[0]["session_id"] == session_id

        # 3. Call Dead-Man's Switch lease reaper endpoint
        reap_resp = await client.post(
            "/api/v1/c2/leases/reap",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reap_resp.status_code == 200
        assert reap_resp.json()["reaped_count"] == 0
        assert reap_resp.json()["dry_run"] is False


@pytest.mark.asyncio
async def test_worker_leases_and_dead_man_switch_api_lifecycle(
    auth_headers: dict[str, str],
) -> None:
    session_id = new_uuid7()
    ctx = TenantContext(
        tenant_id=auth_headers["X-Tenant-ID"],
        workspace_id=auth_headers["X-Workspace-ID"],
        actor_id=auth_headers["X-Actor-ID"],
        role=Role(auth_headers["X-Role"]),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        sdk = ArgusC2Client(ctx, client=client)

        # 1. Register session
        session = await sdk.register_session(
            session_id=session_id,
            workflow_id="wf_lease_test",
            agent_name="lease_agent",
            framework=AgentFramework.LANGGRAPH,
        )
        assert session.session_id == session_id

        # 2. Worker heartbeat
        hb = await sdk.heartbeat(
            session_id=session_id,
            worker_id="pod-integration-1",
            ttl_seconds=45.0,
        )
        assert hb.directive == "CONTINUE"
        assert hb.worker_id == "pod-integration-1"
        assert hb.ttl_remaining_seconds > 0.0

        # 3. Query active lease via SDK
        lease = await sdk.get_lease(session_id)
        assert lease is not None
        assert lease.worker_id == "pod-integration-1"
        assert lease.ttl_seconds == 45.0
        assert lease.is_expired is False

        # 4. List leases via SDK
        all_leases = await sdk.list_leases(active_only=True)
        assert len(all_leases) == 1
        assert all_leases[0].session_id == session_id

        # 5. Dry-run reap sweep
        dry_reap = await sdk.reap_expired_leases(dry_run=True)
        assert dry_reap["dry_run"] is True
        assert dry_reap["reaped_count"] == 0

        # 6. Graceful lease release via SDK
        release_res = await sdk.release_lease(
            session_id=session_id,
            worker_id="pod-integration-1",
            reason="Work completed gracefully",
        )
        assert release_res["status"] == "RELEASED"

        # 7. Verify lease is now gone
        assert await sdk.get_lease(session_id) is None
        empty_leases = await sdk.list_leases(active_only=True)
        assert len(empty_leases) == 0


@pytest.mark.asyncio
async def test_governance_check_and_reset_loop_endpoints(auth_headers: dict[str, str]) -> None:
    session_id = str(new_uuid7())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. Step 1: Normal tool call
        r1 = await client.post(
            "/api/v1/governance/check-loop",
            headers=auth_headers,
            json={
                "session_id": session_id,
                "tool_name": "lookup_customer",
                "tool_args": {"id": 100},
            },
        )
        assert r1.status_code == 200
        assert not r1.json()["tripped"]
        assert r1.json()["recommended_action"] == "ALLOW"

        # 2. Step 2 & 3: Repeat tool call -> Trips Tier 1
        await client.post(
            "/api/v1/governance/check-loop",
            headers=auth_headers,
            json={
                "session_id": session_id,
                "tool_name": "lookup_customer",
                "tool_args": {"id": 100},
            },
        )
        r3 = await client.post(
            "/api/v1/governance/check-loop",
            headers=auth_headers,
            json={
                "session_id": session_id,
                "tool_name": "lookup_customer",
                "tool_args": {"id": 100},
            },
        )
        assert r3.status_code == 200
        assert r3.json()["tripped"]
        assert r3.json()["trip_tier"] == 1
        assert r3.json()["reason"] == "EXACT_TOOL_LOOP"
        assert r3.json()["recommended_action"] == "PAUSE_FOR_C2"

        # 3. Reset loop with VIEWER role -> 403 Forbidden (requires OPERATOR/ADMIN)
        viewer_headers = dict(auth_headers)
        viewer_headers["X-Role"] = "VIEWER"
        r_reset_forbidden = await client.post(
            f"/api/v1/governance/reset-loop/{session_id}",
            headers=viewer_headers,
        )
        assert r_reset_forbidden.status_code == 403

        # 4. Reset loop with OPERATOR/ADMIN auth
        r_reset = await client.post(
            f"/api/v1/governance/reset-loop/{session_id}",
            headers=auth_headers,
        )
        assert r_reset.status_code == 200
        assert r_reset.json()["status"] == "ok"

        # 5. Subsequent call is treated as Step 1 (not tripped)
        r_after = await client.post(
            "/api/v1/governance/check-loop",
            headers=auth_headers,
            json={
                "session_id": session_id,
                "tool_name": "lookup_customer",
                "tool_args": {"id": 100},
            },
        )
        assert r_after.status_code == 200
        assert not r_after.json()["tripped"]


@pytest.mark.asyncio
async def test_governance_check_budget_with_dynamic_tokens_and_http_402(
    auth_headers: dict[str, str],
) -> None:
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
        workflow_id="wf_budget_test",
        agent_name="budget_tester",
        framework=AgentFramework.LANGGRAPH,
        budget_cap_usd=0.05,
    )
    await container.control_store.create_session(ctx, session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. Dynamic token pricing: Claude 3.5 Sonnet (1000 prompt, 500 completion = $0.0105)
        r1 = await client.post(
            "/api/v1/governance/check-budget",
            headers=auth_headers,
            json={
                "session_id": str(session_id),
                "hard_cap_usd": 0.05,
                "model_name": "claude-3-5-sonnet-20241022",
                "estimated_prompt_tokens": 1000,
                "estimated_completion_tokens": 500,
            },
        )
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["allowed"] is True
        assert data1["status"] == "RUNNING"
        assert data1["current_spend_usd"] == pytest.approx(0.0105, abs=1e-4)
        assert data1["warning_tripped"] is False

        # 2. Spend 0.032 -> Total 0.0425 (85% of 0.05 cap) -> Soft warning tripped
        r2 = await client.post(
            "/api/v1/governance/check-budget",
            headers=auth_headers,
            json={
                "session_id": str(session_id),
                "hard_cap_usd": 0.05,
                "requested_usd": 0.032,
            },
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["allowed"] is True
        assert data2["warning_tripped"] is True
        assert "Budget warning" in data2["message"]

        # 3. Spend 0.020 with raise_on_trip=True -> Exceeds 0.05 cap -> HTTP 402 Payment Required!
        r3 = await client.post(
            "/api/v1/governance/check-budget",
            headers=auth_headers,
            json={
                "session_id": str(session_id),
                "hard_cap_usd": 0.05,
                "requested_usd": 0.020,
                "raise_on_trip": True,
            },
        )
        assert r3.status_code == 402
        detail = r3.json()["detail"]
        assert detail["status"] == "TRIPPED_BUDGET"
        assert detail["error"] == "BUDGET_EXCEEDED"

        # 4. Verify session transitioned to TRIPPED_BUDGET
        updated_sess = await container.control_store.get_session(ctx, session_id)
        assert updated_sess.status == SessionStatus.TRIPPED_BUDGET

        # 5. Release 0.025 unused reservation via /release-budget
        r_release = await client.post(
            "/api/v1/governance/release-budget",
            headers=auth_headers,
            json={
                "session_id": str(session_id),
                "amount_usd": 0.025,
            },
        )
        assert r_release.status_code == 200
        assert r_release.json()["updated_spend_usd"] == pytest.approx(0.0175, abs=1e-4)


@pytest.mark.asyncio
async def test_mcp_jsonrpc_gateway_endpoints(auth_headers: dict[str, str]) -> None:
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
        workflow_id="wf_mcp",
        agent_name="mcp_worker",
        framework=AgentFramework.CREWAI,
        budget_cap_usd=50.0,
        status=SessionStatus.RUNNING,
    )
    await container.control_store.create_session(ctx, session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. tools/list JSON-RPC request
        rpc_list = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/list",
            "params": {
                "tools": [
                    {"name": "lookup_user", "description": "Safe lookup tool"},
                    {"name": "drop_table", "description": "Destructive drop table tool"},
                ]
            },
        }
        res_list = await client.post(
            "/api/v1/governance/mcp/rpc",
            headers=auth_headers,
            json=rpc_list,
        )
        assert res_list.status_code == 200
        data_list = res_list.json()
        assert data_list["id"] == 101
        assert len(data_list["result"]["tools"]) == 2

        # 2. tools/call JSON-RPC request (destructive tool) -> paused for C2
        rpc_call = {
            "jsonrpc": "2.0",
            "id": 102,
            "method": "tools/call",
            "params": {
                "name": "drop_table",
                "arguments": {"table": "accounts_ledger"},
                "session_id": str(session_id),
                "estimated_cost_usd": 0.05,
                "hard_cap_usd": 50.0,
            },
        }
        res_call = await client.post(
            "/api/v1/governance/mcp/rpc",
            headers=auth_headers,
            json=rpc_call,
        )
        assert res_call.status_code == 200
        data_call = res_call.json()
        assert data_call["id"] == 102
        assert data_call["error"]["code"] == -32001
        assert data_call["error"]["data"]["status"] == "PAUSED_C2"

        # Session should now be transitioned to PAUSED_C2
        updated_sess = await container.control_store.get_session(ctx, session_id)
        assert updated_sess.status == SessionStatus.PAUSED_C2


@pytest.mark.asyncio
async def test_c2_pending_tools_multitenant_isolation(auth_headers: dict[str, str]) -> None:
    container = get_container()
    session_id = new_uuid7()

    # Intercept tool under tenant 'test_tenant'
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        r_intercept = await client.post(
            "/api/v1/governance/mcp/intercept",
            headers=auth_headers,
            json={
                "session_id": str(session_id),
                "tool_call_id": "call_sec_777",
                "tool_name": "delete_audit_logs",
                "tool_args": {"target": "all"},
                "estimated_cost_usd": 0.01,
                "hard_cap_usd": 10.0,
            },
        )
        assert r_intercept.status_code == 200

        # Query pending tools using Tenant A auth headers
        res_tenant_a = await client.get(
            f"/api/v1/c2/{session_id}/pending-tools",
            headers=auth_headers,
        )
        assert res_tenant_a.status_code == 200
        tools_a = res_tenant_a.json()
        assert len(tools_a) == 1
        assert tools_a[0]["tool_name"] == "delete_audit_logs"

        # Query pending tools as Tenant B (different tenant ID in baggage/headers)
        tenant_b_ctx = TenantContext(
            tenant_id="other_corp",
            workspace_id="ws_b",
            actor_id="op_b",
            role=Role.ADMIN,
        )
        tenant_b_token = container.authenticator.issue_token(tenant_b_ctx)
        tenant_b_headers = {"Authorization": f"Bearer {tenant_b_token}"}
        res_tenant_b = await client.get(
            f"/api/v1/c2/{session_id}/pending-tools",
            headers=tenant_b_headers,
        )
        assert res_tenant_b.status_code == 200
        tools_b = res_tenant_b.json()
        assert len(tools_b) == 0  # Strictly isolated across tenant boundaries!


@pytest.mark.asyncio
async def test_c2_presets_and_timeline_endpoints(auth_headers: dict[str, str]) -> None:
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
        workflow_id="wf_c2_test",
        agent_name="c2_agent",
        framework=AgentFramework.LANGGRAPH,
        budget_cap_usd=20.0,
        status=SessionStatus.RUNNING,
    )
    await container.control_store.create_session(ctx, session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. GET /api/v1/c2/presets
        r_presets = await client.get("/api/v1/c2/presets", headers=auth_headers)
        assert r_presets.status_code == 200
        presets_data = r_presets.json()
        assert len(presets_data) >= 4
        preset_ids = [p["preset_id"] for p in presets_data]
        assert "safe-fallback-plan" in preset_ids
        assert "force-sandbox-replica" in preset_ids

        # 2. Pause session for C2
        r_pause = await client.post(
            f"/api/v1/c2/{session_id}/pause",
            headers=auth_headers,
            json={"operator_id": "admin_user", "reason": "Testing C2 presets"},
        )
        assert r_pause.status_code == 200
        assert r_pause.json()["status"] == "PAUSED_C2"

        # 3. Create initial checkpoint
        r_cp0 = await client.post(
            f"/api/v1/c2/{session_id}/checkpoints",
            headers=auth_headers,
            json={
                "node_name": "agent_init",
                "step_index": 0,
                "memory_state": {"plan": ["drop table test"], "env": "prod"},
            },
        )
        assert r_cp0.status_code == 200
        cp0_id = r_cp0.json()["checkpoint_id"]

        # 4. Apply preset 'safe-fallback-plan'
        r_apply = await client.post(
            f"/api/v1/c2/{session_id}/apply-preset/safe-fallback-plan",
            headers=auth_headers,
            json={
                "operator_id": "admin_user",
                "expected_parent_checkpoint_id": cp0_id,
                "reason": "Safe fallback intervention",
            },
        )
        assert r_apply.status_code == 200
        cp1_data = r_apply.json()
        assert cp1_data["parent_checkpoint_id"] == cp0_id
        assert "read-only schema" in cp1_data["memory_state"]["plan"][0]

        # 5. GET /api/v1/c2/{session_id}/checkpoints (full timeline)
        r_timeline = await client.get(
            f"/api/v1/c2/{session_id}/checkpoints",
            headers=auth_headers,
        )
        assert r_timeline.status_code == 200
        timeline = r_timeline.json()
        assert len(timeline) == 2
        assert timeline[0]["checkpoint_id"] == cp0_id
        assert timeline[1]["checkpoint_id"] == cp1_data["checkpoint_id"]

        # 6. Test optimistic concurrency conflict (stale parent checkpoint ID) -> HTTP 409
        r_conflict = await client.post(
            f"/api/v1/c2/{session_id}/patch",
            headers=auth_headers,
            json={
                "operator_id": "admin_user",
                "expected_parent_checkpoint_id": cp0_id,  # Stale! Latest is cp1
                "patches": [{"op": "replace", "path": "/env", "value": "dev"}],
            },
        )
        assert r_conflict.status_code == 409

        # 7. Test invalid RFC 6902 patch (e.g. test mismatch) -> HTTP 400
        r_bad_patch = await client.post(
            f"/api/v1/c2/{session_id}/patch",
            headers=auth_headers,
            json={
                "operator_id": "admin_user",
                "expected_parent_checkpoint_id": cp1_data["checkpoint_id"],
                "patches": [
                    {"op": "test", "path": "/env", "value": "staging"},  # env is 'prod'
                ],
            },
        )
        assert r_bad_patch.status_code == 400
        assert "test" in r_bad_patch.json()["detail"].lower()


@pytest.mark.asyncio
async def test_audit_ledger_verification_and_export_lifecycle(
    auth_headers: dict[str, str],
) -> None:
    session_id = new_uuid7()
    ctx = TenantContext(
        tenant_id=auth_headers["X-Tenant-ID"],
        workspace_id=auth_headers["X-Workspace-ID"],
        actor_id=auth_headers["X-Actor-ID"],
        role=Role(auth_headers["X-Role"]),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        sdk = ArgusC2Client(ctx, client=client)

        # 1. Register session
        await sdk.register_session(
            session_id=session_id,
            workflow_id="wf_audit_test",
            agent_name="audit_agent",
            framework=AgentFramework.LANGGRAPH,
        )

        # 2. Perform operator interventions to generate audit entries
        r_pause = await client.post(
            f"/api/v1/c2/{session_id}/pause",
            headers=auth_headers,
            json={"operator_id": "admin_user", "reason": "Manual review pause"},
        )
        assert r_pause.status_code == 200

        r_resume = await client.post(
            f"/api/v1/c2/{session_id}/resume",
            headers=auth_headers,
            json={"operator_id": "admin_user", "reason": "Manual review resume"},
        )
        assert r_resume.status_code == 200

        # 3. Retrieve audit log via SDK
        log_resp = await sdk.get_audit_log(session_id)
        assert log_resp.chain_verified is True
        assert len(log_resp.entries) == 2
        assert log_resp.verification_report is not None
        assert log_resp.verification_report.is_valid is True
        assert log_resp.verification_report.total_entries == 2

        # 4. Dedicated verification attestation endpoint via SDK
        verify_report = await sdk.verify_audit_log(session_id)
        assert verify_report.is_valid is True
        assert verify_report.total_entries == 2
        assert verify_report.tip_hash == log_resp.entries[-1].entry_hash
        assert verify_report.violation_type is None

        # 5. Export in JSON, JSONL, and CSV formats
        r_json = await client.get(
            f"/api/v1/c2/{session_id}/audit-log/export?format=json",
            headers=auth_headers,
        )
        assert r_json.status_code == 200
        assert r_json.headers["content-type"] == "application/json"
        assert f'filename="audit_{session_id}.json"' in r_json.headers["content-disposition"]
        assert len(r_json.json()) == 2

        r_jsonl = await client.get(
            f"/api/v1/c2/{session_id}/audit-log/export?format=jsonl",
            headers=auth_headers,
        )
        assert r_jsonl.status_code == 200
        lines = [ln for ln in r_jsonl.text.strip().split("\n") if ln.strip()]
        assert len(lines) == 2

        r_csv = await client.get(
            f"/api/v1/c2/{session_id}/audit-log/export?format=csv",
            headers=auth_headers,
        )
        assert r_csv.status_code == 200
        assert "audit_id,created_at,event_type" in r_csv.text

        # 6. Query audit log with filters via SDK
        query_res = await sdk.query_audit_entries(session_id=session_id, event_type="C2_PAUSE")
        assert query_res.total_count == 1
        assert len(query_res.entries) == 1
        assert query_res.entries[0].event_type == "C2_PAUSE"


