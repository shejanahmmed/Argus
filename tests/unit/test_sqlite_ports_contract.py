"""Unit and contract tests for WAL-mode SQLite hexagonal storage adapters."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from argus.adapters_infra.sqlite_store import (
    SqliteAuditStore,
    SqliteBudgetStore,
    SqliteControlStore,
    SqliteEngine,
    SqliteTraceStore,
)
from argus.core.errors import BudgetExceededError, CheckpointConflictError, TenantIsolationError
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
from argus.ports.repositories import AuditStore, BudgetStore, ControlStore, TraceStore


@pytest.fixture
def ctx() -> TenantContext:
    return TenantContext(
        tenant_id="tenant_sql",
        workspace_id="ws_sql",
        actor_id="op_sql",
        role=Role.ADMIN,
    )


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[SqliteEngine]:
    db_file = tmp_path / "test_argus.db"
    engine = SqliteEngine(db_file)
    yield engine
    engine.close()


@pytest.mark.asyncio
async def test_sqlite_trace_store_subtree_and_isolation(
    ctx: TenantContext, sqlite_engine: SqliteEngine
) -> None:
    store = SqliteTraceStore(sqlite_engine)
    assert isinstance(store, TraceStore)

    session_id = new_uuid7()
    trace_id = new_uuid7()
    root_id = new_uuid7()
    child_id = new_uuid7()
    t0 = utc_now()
    root_order = build_dotted_order(t0, root_id)
    child_order = build_dotted_order(t0, child_id, parent_dotted_order=root_order)

    root_span = ArgusSpan(
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=root_id,
        parent_span_id=None,
        dotted_order=root_order,
        name="root_agent",
        span_kind=SpanKind.AGENT,
        operation_name=OperationName.INVOKE_AGENT,
        started_at=t0,
    )
    child_span = ArgusSpan(
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=child_id,
        parent_span_id=root_id,
        dotted_order=child_order,
        name="child_llm",
        span_kind=SpanKind.LLM,
        operation_name=OperationName.CHAT,
        started_at=t0,
    )

    written = await store.append_spans(ctx, [child_span, root_span])
    assert written == 2

    subtree = await store.get_trace_subtree(ctx, root_order)
    assert [s.span_id for s in subtree] == [root_id, child_id]

    session_spans = await store.get_session_spans(ctx, session_id)
    assert len(session_spans) == 2

    other_ctx = TenantContext(
        tenant_id="other_tenant",
        workspace_id="ws_sql",
        actor_id="attacker",
        role=Role.ADMIN,
    )
    with pytest.raises(TenantIsolationError):
        await store.append_spans(other_ctx, [root_span])


@pytest.mark.asyncio
async def test_sqlite_control_store_checkpoints_and_optimistic_lock(
    ctx: TenantContext, sqlite_engine: SqliteEngine
) -> None:
    store = SqliteControlStore(sqlite_engine)
    assert isinstance(store, ControlStore)

    session_id = new_uuid7()
    session = AgentSession(
        session_id=session_id,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        workflow_id="wf_sql",
        agent_name="sql_agent",
        framework=AgentFramework.LANGGRAPH,
        budget_cap_usd=25.0,
    )
    await store.create_session(ctx, session)

    updated = await store.add_session_cost(ctx, session_id, 1.25)
    assert updated.accumulated_cost_usd == 1.25

    paused = await store.transition_session(
        ctx, session_id, SessionStatus.RUNNING, SessionStatus.PAUSED_C2
    )
    assert paused.status == SessionStatus.PAUSED_C2

    cp1_id = new_uuid7()
    cp1 = CheckpointRecord(
        checkpoint_id=cp1_id,
        parent_checkpoint_id=None,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        node_name="node_a",
        step_index=0,
        memory_state={"k": "v1"},
    )
    await store.save_checkpoint(ctx, cp1, expected_parent_id=None)

    latest = await store.get_latest_checkpoint(ctx, session_id)
    assert latest is not None
    assert latest.checkpoint_id == cp1_id

    # Stale expected_parent_id must raise CheckpointConflictError
    cp_stale = CheckpointRecord(
        checkpoint_id=new_uuid7(),
        parent_checkpoint_id=None,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        node_name="node_b",
        step_index=1,
        memory_state={"k": "v2"},
    )
    with pytest.raises(CheckpointConflictError):
        await store.save_checkpoint(ctx, cp_stale, expected_parent_id=None)

    # Verify list_checkpoints
    cps = await store.list_checkpoints(ctx, session_id)
    assert len(cps) == 1
    assert cps[0].checkpoint_id == cp1_id


@pytest.mark.asyncio
async def test_sqlite_budget_and_audit_stores(
    ctx: TenantContext, sqlite_engine: SqliteEngine
) -> None:
    budget_store = SqliteBudgetStore(sqlite_engine)
    audit_store = SqliteAuditStore(sqlite_engine)
    assert isinstance(budget_store, BudgetStore)
    assert isinstance(audit_store, AuditStore)

    session_id = new_uuid7()
    spend = await budget_store.reserve_budget(ctx, session_id, 4.0, 10.0)
    assert spend == 4.0
    assert await budget_store.get_spend(ctx, session_id) == 4.0

    with pytest.raises(BudgetExceededError):
        await budget_store.reserve_budget(ctx, session_id, 7.0, 10.0)

    # Release 1.5 of reserved budget -> spend becomes 2.5
    refunded = await budget_store.release_budget(ctx, session_id, 1.5)
    assert refunded == 2.5
    assert await budget_store.get_spend(ctx, session_id) == 2.5

    # Now reserving 7.0 succeeds within 10.0 cap (2.5 + 7.0 = 9.5)
    spend_again = await budget_store.reserve_budget(ctx, session_id, 7.0, 10.0)
    assert spend_again == 9.5

    await audit_store.append_event(
        ctx,
        session_id=session_id,
        event_type="C2_PAUSE",
        payload={"reason": "first event"},
    )
    await audit_store.append_event(
        ctx,
        session_id=session_id,
        event_type="C2_RESUME",
        payload={"reason": "second event"},
    )

    entries = await audit_store.get_session_audit_log(ctx, session_id)
    assert len(entries) == 2
    assert await audit_store.verify_session_chain(ctx, session_id) is True

    # Test detailed cryptographic chain verification
    detailed_report = await audit_store.verify_session_chain_detailed(ctx, session_id)
    assert detailed_report.is_valid is True
    assert detailed_report.total_entries == 2
    assert detailed_report.tip_hash == entries[-1].entry_hash
    assert detailed_report.violation_type is None

    # Test workspace audit query with filtering and pagination
    query_pause, total_pause = await audit_store.query_audit_entries(
        ctx, session_id=session_id, event_type="C2_PAUSE"
    )
    assert total_pause == 1
    assert len(query_pause) == 1
    assert query_pause[0].event_type == "C2_PAUSE"

    all_paged, total_all = await audit_store.query_audit_entries(
        ctx, session_id=session_id, limit=1, offset=1
    )
    assert total_all == 2
    assert len(all_paged) == 1
    assert all_paged[0].event_type == "C2_RESUME"


def test_sqlite_engine_pragmas_and_wal_mode(tmp_path: Path) -> None:
    db_file = tmp_path / "test_wal.db"
    disk_engine = SqliteEngine(db_file)
    try:
        assert disk_engine.active_journal_mode == "wal"
        cur = disk_engine.conn.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1
        cur = disk_engine.conn.execute("PRAGMA busy_timeout")
        assert cur.fetchone()[0] == 5000
    finally:
        disk_engine.close()

    mem_engine = SqliteEngine(":memory:")
    try:
        assert mem_engine.active_journal_mode == "memory"
    finally:
        mem_engine.close()


def test_sqlite_engine_diagnostics_and_integrity(tmp_path: Path) -> None:
    db_file = tmp_path / "test_diag.db"
    engine = SqliteEngine(db_file)
    try:
        diag = engine.get_diagnostics()
        assert diag["integrity_check"] == "ok"
        assert diag["journal_mode"] == "wal"
        assert diag["page_size"] > 0
        assert diag["page_count"] > 0
        assert diag["database_size_bytes"] > 0
        assert "table_counts" in diag
        assert diag["table_counts"]["sessions"] == 0
        assert diag["table_counts"]["checkpoints"] == 0
        assert diag["table_counts"]["spans"] == 0
        assert diag["table_counts"]["budgets"] == 0
        assert diag["table_counts"]["audit_entries"] == 0
    finally:
        engine.close()


def test_sqlite_engine_wal_checkpoint(tmp_path: Path) -> None:
    db_file = tmp_path / "test_checkpoint.db"
    engine = SqliteEngine(db_file)
    try:
        busy, log_frames, checkpointed_frames = engine.checkpoint_wal("PASSIVE")
        assert busy == 0
        assert log_frames >= 0
        assert checkpointed_frames >= 0

        # TRUNCATE mode
        busy, log_frames, _checkpointed = engine.checkpoint_wal("TRUNCATE")
        assert busy == 0

        with pytest.raises(ValueError, match="Invalid WAL checkpoint mode"):
            engine.checkpoint_wal("INVALID_MODE")
    finally:
        engine.close()


def test_production_migrations_ddl_syntax() -> None:
    migration_file = (
        Path(__file__).resolve().parents[2] / "src" / "argus" / "adapters_infra" / "migrations.sql"
    )
    assert migration_file.exists(), f"Migrations file {migration_file} must exist."
    content = migration_file.read_text(encoding="utf-8")

    # Verify PostgreSQL tables and indexes
    assert "CREATE TABLE IF NOT EXISTS argus_sessions" in content
    assert "CREATE TABLE IF NOT EXISTS argus_checkpoints" in content
    assert "CREATE TABLE IF NOT EXISTS argus_audit_ledger" in content
    assert "CREATE TABLE IF NOT EXISTS argus_budgets" in content
    assert "CREATE TABLE IF NOT EXISTS argus_spans" in content
    assert "varchar_pattern_ops" in content

    # Verify ClickHouse schema
    assert "CREATE DATABASE IF NOT EXISTS argus_telemetry" in content
    assert "CREATE TABLE IF NOT EXISTS argus_telemetry.argus_spans" in content
    assert "ENGINE = MergeTree()" in content
    assert "ORDER BY (tenant_id, workspace_id, session_id, dotted_order)" in content
