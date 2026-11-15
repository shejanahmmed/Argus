"""Integration tests for SQLite persistence durability across restarts and concurrency."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from argus.api.app import app
from argus.api.dependencies import AppContainer, get_container
from argus.core.config import ArgusSettings
from argus.core.ids import build_dotted_order, new_uuid7, utc_now
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    ArgusSpan,
    CheckpointRecord,
    OperationName,
    SessionStatus,
    SpanKind,
)
from argus.core.tenancy import Role, TenantContext


@pytest.mark.asyncio
async def test_sqlite_durable_restart_persistence(tmp_path: Path) -> None:
    """Verify that sessions, checkpoints, spans, and audit chains survive container restarts."""
    db_file = tmp_path / "argus_restart_test.db"
    ctx = TenantContext(
        tenant_id="tenant_durable",
        workspace_id="ws_durable",
        actor_id="operator_durable",
        role=Role.ADMIN,
    )

    session_id = new_uuid7()
    cp1_id = new_uuid7()
    t0 = utc_now()
    root_id = new_uuid7()
    child_id = new_uuid7()
    root_order = build_dotted_order(t0, root_id)
    child_order = build_dotted_order(t0, child_id, parent_dotted_order=root_order)

    # -------------------------------------------------------------------------
    # Phase 1: Populate State in Initial Container
    # -------------------------------------------------------------------------
    container1 = AppContainer(backend="sqlite", db_path=str(db_file))
    try:
        # 1. Create Session
        session = AgentSession(
            session_id=session_id,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            workflow_id="wf_durable",
            agent_name="durable_agent",
            framework=AgentFramework.LANGGRAPH,
            budget_cap_usd=25.0,
        )
        await container1.control_store.create_session(ctx, session)
        await container1.control_store.add_session_cost(ctx, session_id, 2.5)
        await container1.control_store.transition_session(
            ctx, session_id, SessionStatus.RUNNING, SessionStatus.PAUSED_C2
        )

        # 2. Save Checkpoint
        checkpoint = CheckpointRecord(
            checkpoint_id=cp1_id,
            parent_checkpoint_id=None,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=session_id,
            node_name="node_durable",
            step_index=0,
            memory_state={"persisted_key": "persisted_value_123"},
        )
        await container1.control_store.save_checkpoint(ctx, checkpoint, expected_parent_id=None)

        # 3. Append Spans
        root_span = ArgusSpan(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=session_id,
            trace_id=root_id,
            span_id=root_id,
            parent_span_id=None,
            dotted_order=root_order,
            name="durable_root",
            span_kind=SpanKind.AGENT,
            operation_name=OperationName.INVOKE_AGENT,
            started_at=t0,
        )
        child_span = ArgusSpan(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=session_id,
            trace_id=root_id,
            span_id=child_id,
            parent_span_id=root_id,
            dotted_order=child_order,
            name="durable_child",
            span_kind=SpanKind.TOOL,
            operation_name=OperationName.EXECUTE_TOOL,
            started_at=t0,
        )
        await container1.trace_store.append_spans(ctx, [root_span, child_span])

        # 4. Reserve Budget ($5.0)
        reserved = await container1.budget_store.reserve_budget(ctx, session_id, 5.0, 25.0)
        assert reserved == 5.0

        # 5. Append Tamper-Evident SHA-256 Audit Log Chain
        await container1.audit_store.append_event(
            ctx,
            session_id=session_id,
            event_type="C2_PAUSE",
            payload={"reason": "pre-restart test pause"},
        )
        await container1.audit_store.append_event(
            ctx,
            session_id=session_id,
            event_type="C2_EDIT_MEMORY",
            payload={"patch": [{"op": "replace", "path": "/k", "value": "v2"}]},
        )
        await container1.audit_store.append_event(
            ctx,
            session_id=session_id,
            event_type="C2_RESUME",
            payload={"reason": "pre-restart test resume"},
        )

        # Verify initial diagnostics
        assert container1._sqlite_engine is not None
        diag1 = container1._sqlite_engine.get_diagnostics()
        assert diag1["table_counts"]["sessions"] == 1
        assert diag1["table_counts"]["checkpoints"] == 1
        assert diag1["table_counts"]["spans"] == 2
        assert diag1["table_counts"]["budgets"] == 1
        assert diag1["table_counts"]["audit_entries"] == 3
        assert diag1["integrity_check"] == "ok"
    finally:
        # Simulate Process Termination / Restart
        if container1._sqlite_engine is not None:
            container1._sqlite_engine.close()

    # -------------------------------------------------------------------------
    # Phase 2: Instantiate Fresh Container against the Same SQLite DB File
    # -------------------------------------------------------------------------
    container2 = AppContainer(backend="sqlite", db_path=str(db_file))
    try:
        # 1. Verify Session State and Cost
        restarted_session = await container2.control_store.get_session(ctx, session_id)
        assert restarted_session.agent_name == "durable_agent"
        assert restarted_session.status == SessionStatus.PAUSED_C2
        assert restarted_session.accumulated_cost_usd == 2.5
        assert restarted_session.latest_checkpoint_id == cp1_id

        # 2. Verify Checkpoints
        latest_cp = await container2.control_store.get_latest_checkpoint(ctx, session_id)
        assert latest_cp is not None
        assert latest_cp.checkpoint_id == cp1_id
        assert latest_cp.memory_state == {"persisted_key": "persisted_value_123"}

        all_cps = await container2.control_store.list_checkpoints(ctx, session_id)
        assert len(all_cps) == 1
        assert all_cps[0].checkpoint_id == cp1_id

        # 3. Verify Telemetry Spans and Dotted-Order Subtree
        spans = await container2.trace_store.get_session_spans(ctx, session_id)
        assert len(spans) == 2
        assert [s.span_id for s in spans] == [root_id, child_id]

        subtree = await container2.trace_store.get_trace_subtree(ctx, root_order)
        assert len(subtree) == 2
        assert subtree[0].name == "durable_root"
        assert subtree[1].name == "durable_child"

        # 4. Verify Atomic Budget Ledger
        persisted_spend = await container2.budget_store.get_spend(ctx, session_id)
        assert persisted_spend == 5.0

        # Further reserve 3.0 on restarted database -> 8.0
        spend_step2 = await container2.budget_store.reserve_budget(ctx, session_id, 3.0, 25.0)
        assert spend_step2 == 8.0

        # 5. Verify Cryptographic SHA-256 Audit Chain
        audit_entries = await container2.audit_store.get_session_audit_log(ctx, session_id)
        assert len(audit_entries) == 3
        assert audit_entries[0].event_type == "C2_PAUSE"
        assert audit_entries[1].event_type == "C2_EDIT_MEMORY"
        assert audit_entries[2].event_type == "C2_RESUME"

        verification = await container2.audit_store.verify_session_chain_detailed(ctx, session_id)
        assert verification.is_valid is True
        assert verification.total_entries == 3
        assert verification.tip_hash == audit_entries[-1].entry_hash
        assert verification.tampered_entry_index is None

        # Verify Diagnostics
        assert container2._sqlite_engine is not None
        diag2 = container2._sqlite_engine.get_diagnostics()
        assert diag2["integrity_check"] == "ok"
        assert diag2["table_counts"]["sessions"] == 1
        assert diag2["table_counts"]["spans"] == 2
        assert diag2["table_counts"]["audit_entries"] == 3
    finally:
        if container2._sqlite_engine is not None:
            container2._sqlite_engine.close()


@pytest.mark.asyncio
async def test_sqlite_concurrency_stress(tmp_path: Path) -> None:
    """Stress-test SQLite concurrent writes under WAL mode to verify lock serialization."""
    db_file = tmp_path / "argus_concurrency_test.db"
    container = AppContainer(backend="sqlite", db_path=str(db_file))
    ctx = TenantContext(
        tenant_id="tenant_conc",
        workspace_id="ws_conc",
        actor_id="tester",
        role=Role.ADMIN,
    )

    try:
        session_id = new_uuid7()
        session = AgentSession(
            session_id=session_id,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            workflow_id="wf_conc",
            agent_name="conc_agent",
            framework=AgentFramework.CREWAI,
            budget_cap_usd=500.0,
        )
        await container.control_store.create_session(ctx, session)

        async def worker_task(idx: int) -> None:
            span_id = new_uuid7()
            t = utc_now()
            span = ArgusSpan(
                tenant_id=ctx.tenant_id,
                workspace_id=ctx.workspace_id,
                session_id=session_id,
                trace_id=session_id,
                span_id=span_id,
                parent_span_id=None,
                dotted_order=build_dotted_order(t, span_id),
                name=f"conc_span_{idx}",
                span_kind=SpanKind.TOOL,
                operation_name=OperationName.EXECUTE_TOOL,
                started_at=t,
            )
            await container.trace_store.append_spans(ctx, [span])
            await container.budget_store.reserve_budget(ctx, session_id, 1.0, 500.0)

        # Dispatch 30 concurrent tasks
        await asyncio.gather(*(worker_task(i) for i in range(30)))

        # Verify results
        spans = await container.trace_store.get_session_spans(ctx, session_id)
        assert len(spans) == 30
        spend = await container.budget_store.get_spend(ctx, session_id)
        assert spend == 30.0
    finally:
        if container._sqlite_engine is not None:
            container._sqlite_engine.close()


def test_readyz_diagnostics_endpoint(tmp_path: Path) -> None:
    """Verify /readyz endpoint with ?diagnostics=true returns structured diagnostic metadata."""
    client = TestClient(app)
    container = get_container()
    db_file = tmp_path / "readyz_test.db"

    old_backend = container._backend
    old_engine = container._sqlite_engine
    old_settings = container.settings

    try:
        container.settings = ArgusSettings(storage_backend="sqlite", db_path=str(db_file))
        container._backend = "sqlite"
        container._db_path = str(db_file)
        container._init_stores()

        res = client.get("/readyz?diagnostics=true")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "READY"
        assert data["storage_backend"] == "sqlite"
        assert "diagnostics" in data
        diag = data["diagnostics"]
        assert diag["integrity_check"] == "ok"
        assert diag["journal_mode"] == "wal"
        assert "table_counts" in diag
    finally:
        if container._sqlite_engine is not None:
            container._sqlite_engine.close()
        container.settings = old_settings
        container._backend = old_backend
        container._sqlite_engine = old_engine
        container._init_stores()
