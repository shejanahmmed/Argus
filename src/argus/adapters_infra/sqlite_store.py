"""Durable WAL-mode SQLite adapters implementing Argus hexagonal repository ports.

Provides zero-spend, zero-external-daemon relational and analytical persistence
for sessions, checkpoints, spans, atomic budgets, and SHA-256 hash-chained audit logs.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from argus.core.errors import (
    BudgetExceededError,
    CheckpointConflictError,
    EntityNotFoundError,
    InvalidStateTransitionError,
)
from argus.core.ids import new_uuid7
from argus.core.schemas import (
    GENESIS_AUDIT_HASH,
    AgentSession,
    ArgusSpan,
    AuditLogEntry,
    CheckpointRecord,
    SessionStatus,
)
from argus.core.tenancy import TenantContext

_SCHEMA_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS argus_sessions (
    session_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_tenant
    ON argus_sessions (tenant_id, workspace_id);

CREATE TABLE IF NOT EXISTS argus_checkpoints (
    seq_id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_session
    ON argus_checkpoints (session_id, seq_id ASC);

CREATE TABLE IF NOT EXISTS argus_spans (
    span_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    dotted_order TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spans_session_dotted
    ON argus_spans (tenant_id, workspace_id, session_id, dotted_order ASC);

CREATE INDEX IF NOT EXISTS idx_spans_subtree
    ON argus_spans (tenant_id, workspace_id, dotted_order ASC);

CREATE TABLE IF NOT EXISTS argus_budgets (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    accumulated_usd REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (tenant_id, workspace_id, session_id)
);

CREATE TABLE IF NOT EXISTS argus_audit_ledger (
    seq_id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    prev_entry_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_session
    ON argus_audit_ledger (tenant_id, workspace_id, session_id, seq_id ASC);
"""


class SqliteEngine:
    """Shared WAL-mode SQLite connection manager with coroutine lock serialization."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_DDL)
        self._conn.commit()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def reset_tables(self) -> None:
        """Truncate all Argus tables for deterministic test resets."""
        self._conn.executescript(
            """
            DELETE FROM argus_spans;
            DELETE FROM argus_checkpoints;
            DELETE FROM argus_sessions;
            DELETE FROM argus_budgets;
            DELETE FROM argus_audit_ledger;
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class SqliteTraceStore:
    """Durable SQLite implementation of the TraceStore port."""

    def __init__(self, engine: SqliteEngine) -> None:
        self._engine = engine

    async def append_spans(self, ctx: TenantContext, spans: Sequence[ArgusSpan]) -> int:
        for span in spans:
            ctx.assert_same_tenant(span.tenant_id, span.workspace_id)
        if not spans:
            return 0
        async with self._engine.lock:
            rows = [
                (
                    str(s.span_id),
                    s.tenant_id,
                    s.workspace_id,
                    str(s.session_id),
                    s.dotted_order,
                    s.model_dump_json(),
                )
                for s in spans
            ]
            self._engine.conn.executemany(
                """
                INSERT OR REPLACE INTO argus_spans
                (span_id, tenant_id, workspace_id, session_id, dotted_order, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._engine.conn.commit()
        return len(spans)

    async def get_trace_subtree(
        self,
        ctx: TenantContext,
        root_dotted_order: str,
    ) -> list[ArgusSpan]:
        prefix_dot = f"{root_dotted_order}.%"
        async with self._engine.lock:
            cur = self._engine.conn.execute(
                """
                SELECT payload_json FROM argus_spans
                WHERE tenant_id = ? AND workspace_id = ?
                  AND (dotted_order = ? OR dotted_order LIKE ?)
                ORDER BY dotted_order ASC
                """,
                (ctx.tenant_id, ctx.workspace_id, root_dotted_order, prefix_dot),
            )
            rows = cur.fetchall()
        return [ArgusSpan.model_validate_json(row["payload_json"]) for row in rows]

    async def get_session_spans(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[ArgusSpan]:
        async with self._engine.lock:
            cur = self._engine.conn.execute(
                """
                SELECT payload_json FROM argus_spans
                WHERE tenant_id = ? AND workspace_id = ? AND session_id = ?
                ORDER BY dotted_order ASC
                """,
                (ctx.tenant_id, ctx.workspace_id, str(session_id)),
            )
            rows = cur.fetchall()
        return [ArgusSpan.model_validate_json(row["payload_json"]) for row in rows]


class SqliteControlStore:
    """Durable SQLite implementation of the ControlStore port."""

    def __init__(self, engine: SqliteEngine) -> None:
        self._engine = engine

    async def create_session(self, ctx: TenantContext, session: AgentSession) -> AgentSession:
        ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
        async with self._engine.lock:
            self._engine.conn.execute(
                """
                INSERT OR REPLACE INTO argus_sessions
                (session_id, tenant_id, workspace_id, status, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(session.session_id),
                    session.tenant_id,
                    session.workspace_id,
                    session.status.value,
                    session.model_dump_json(),
                ),
            )
            self._engine.conn.commit()
        return session

    def _get_session_sync(self, session_id: uuid.UUID) -> AgentSession | None:
        cur = self._engine.conn.execute(
            "SELECT payload_json FROM argus_sessions WHERE session_id = ?",
            (str(session_id),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return AgentSession.model_validate_json(row["payload_json"])

    def _save_session_sync(self, session: AgentSession) -> None:
        self._engine.conn.execute(
            """
            UPDATE argus_sessions
            SET status = ?, payload_json = ?
            WHERE session_id = ?
            """,
            (session.status.value, session.model_dump_json(), str(session.session_id)),
        )

    async def get_session(self, ctx: TenantContext, session_id: uuid.UUID) -> AgentSession:
        async with self._engine.lock:
            session = self._get_session_sync(session_id)
        if session is None:
            raise EntityNotFoundError("AgentSession", str(session_id))
        ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
        return session

    async def transition_session(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        expected_status: SessionStatus,
        next_status: SessionStatus,
    ) -> AgentSession:
        async with self._engine.lock:
            session = self._get_session_sync(session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
            if session.status != expected_status:
                raise InvalidStateTransitionError(session.status.value, next_status.value)
            updated = session.transition_to(next_status)
            self._save_session_sync(updated)
            self._engine.conn.commit()
            return updated

    async def save_checkpoint(
        self,
        ctx: TenantContext,
        checkpoint: CheckpointRecord,
        expected_parent_id: uuid.UUID | None,
    ) -> CheckpointRecord:
        ctx.assert_same_tenant(checkpoint.tenant_id, checkpoint.workspace_id)
        async with self._engine.lock:
            session = self._get_session_sync(checkpoint.session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(checkpoint.session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)

            cur = self._engine.conn.execute(
                """
                SELECT checkpoint_id FROM argus_checkpoints
                WHERE session_id = ?
                ORDER BY seq_id DESC LIMIT 1
                """,
                (str(checkpoint.session_id),),
            )
            latest_row = cur.fetchone()
            current_latest_id = (
                uuid.UUID(latest_row["checkpoint_id"]) if latest_row is not None else None
            )

            if current_latest_id != expected_parent_id:
                raise CheckpointConflictError(
                    expected_id=str(expected_parent_id),
                    actual_id=str(current_latest_id) if current_latest_id else None,
                )

            self._engine.conn.execute(
                """
                INSERT INTO argus_checkpoints
                (checkpoint_id, session_id, tenant_id, workspace_id,
                 parent_checkpoint_id, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(checkpoint.checkpoint_id),
                    str(checkpoint.session_id),
                    checkpoint.tenant_id,
                    checkpoint.workspace_id,
                    str(checkpoint.parent_checkpoint_id)
                    if checkpoint.parent_checkpoint_id
                    else None,
                    checkpoint.model_dump_json(),
                ),
            )
            updated_session = session.model_copy(
                update={"latest_checkpoint_id": checkpoint.checkpoint_id}
            )
            self._save_session_sync(updated_session)
            self._engine.conn.commit()
            return checkpoint

    async def get_latest_checkpoint(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> CheckpointRecord | None:
        async with self._engine.lock:
            session = self._get_session_sync(session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)

            cur = self._engine.conn.execute(
                """
                SELECT payload_json FROM argus_checkpoints
                WHERE session_id = ?
                ORDER BY seq_id DESC LIMIT 1
                """,
                (str(session_id),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return CheckpointRecord.model_validate_json(row["payload_json"])

    async def list_sessions(
        self,
        ctx: TenantContext,
    ) -> list[AgentSession]:
        async with self._engine.lock:
            cur = self._engine.conn.execute(
                """
                SELECT payload_json FROM argus_sessions
                WHERE tenant_id = ? AND workspace_id = ?
                """,
                (ctx.tenant_id, ctx.workspace_id),
            )
            rows = cur.fetchall()
        return [AgentSession.model_validate_json(row["payload_json"]) for row in rows]

    async def add_session_cost(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        cost_usd: float,
    ) -> AgentSession:
        async with self._engine.lock:
            session = self._get_session_sync(session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)
            new_cost = round(session.accumulated_cost_usd + max(0.0, cost_usd), 8)
            updated = session.model_copy(update={"accumulated_cost_usd": new_cost})
            self._save_session_sync(updated)
            self._engine.conn.commit()
            return updated


class SqliteBudgetStore:
    """Atomic SQLite implementation of the BudgetStore port."""

    def __init__(self, engine: SqliteEngine) -> None:
        self._engine = engine

    async def reserve_budget(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        requested_usd: float,
        hard_cap_usd: float,
    ) -> float:
        if requested_usd < 0.0:
            raise ValueError("requested_usd cannot be negative.")
        if hard_cap_usd <= 0.0:
            raise ValueError("hard_cap_usd must be positive.")

        async with self._engine.lock:
            cur = self._engine.conn.execute(
                """
                SELECT accumulated_usd FROM argus_budgets
                WHERE tenant_id = ? AND workspace_id = ? AND session_id = ?
                """,
                (ctx.tenant_id, ctx.workspace_id, str(session_id)),
            )
            row = cur.fetchone()
            current = float(row["accumulated_usd"]) if row is not None else 0.0
            projected = round(current + requested_usd, 8)
            if projected > hard_cap_usd:
                raise BudgetExceededError(
                    session_id=str(session_id),
                    accumulated_usd=current,
                    requested_usd=requested_usd,
                    hard_cap_usd=hard_cap_usd,
                )

            self._engine.conn.execute(
                """
                INSERT INTO argus_budgets (tenant_id, workspace_id, session_id, accumulated_usd)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, workspace_id, session_id)
                DO UPDATE SET accumulated_usd = excluded.accumulated_usd
                """,
                (ctx.tenant_id, ctx.workspace_id, str(session_id), projected),
            )
            self._engine.conn.commit()
            return projected

    async def get_spend(self, ctx: TenantContext, session_id: uuid.UUID) -> float:
        async with self._engine.lock:
            cur = self._engine.conn.execute(
                """
                SELECT accumulated_usd FROM argus_budgets
                WHERE tenant_id = ? AND workspace_id = ? AND session_id = ?
                """,
                (ctx.tenant_id, ctx.workspace_id, str(session_id)),
            )
            row = cur.fetchone()
            return float(row["accumulated_usd"]) if row is not None else 0.0


class SqliteAuditStore:
    """Tamper-evident SHA-256 hash-chained SQLite implementation of the AuditStore port."""

    def __init__(self, engine: SqliteEngine) -> None:
        self._engine = engine

    async def append_event(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> AuditLogEntry:
        async with self._engine.lock:
            cur = self._engine.conn.execute(
                """
                SELECT entry_hash FROM argus_audit_ledger
                WHERE tenant_id = ? AND workspace_id = ? AND session_id = ?
                ORDER BY seq_id DESC LIMIT 1
                """,
                (ctx.tenant_id, ctx.workspace_id, str(session_id)),
            )
            last_row = cur.fetchone()
            prev_hash = str(last_row["entry_hash"]) if last_row is not None else GENESIS_AUDIT_HASH

            entry = AuditLogEntry.create_linked(
                audit_id=new_uuid7(),
                tenant_id=ctx.tenant_id,
                workspace_id=ctx.workspace_id,
                session_id=session_id,
                actor_id=ctx.actor_id,
                actor_role=ctx.role,
                event_type=event_type,
                payload=payload,
                prev_entry_hash=prev_hash,
            )

            self._engine.conn.execute(
                """
                INSERT INTO argus_audit_ledger
                (audit_id, tenant_id, workspace_id, session_id,
                 entry_hash, prev_entry_hash, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(entry.audit_id),
                    entry.tenant_id,
                    entry.workspace_id,
                    str(entry.session_id),
                    entry.entry_hash,
                    entry.prev_entry_hash,
                    json.dumps(entry.model_dump(mode="json")),
                ),
            )
            self._engine.conn.commit()
            return entry

    async def get_session_audit_log(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[AuditLogEntry]:
        async with self._engine.lock:
            cur = self._engine.conn.execute(
                """
                SELECT payload_json FROM argus_audit_ledger
                WHERE tenant_id = ? AND workspace_id = ? AND session_id = ?
                ORDER BY seq_id ASC
                """,
                (ctx.tenant_id, ctx.workspace_id, str(session_id)),
            )
            rows = cur.fetchall()
        return [AuditLogEntry.model_validate_json(row["payload_json"]) for row in rows]

    async def verify_session_chain(self, ctx: TenantContext, session_id: uuid.UUID) -> bool:
        entries = await self.get_session_audit_log(ctx, session_id)
        expected_prev = GENESIS_AUDIT_HASH
        for entry in entries:
            if not entry.verify_integrity(expected_prev):
                return False
            expected_prev = entry.entry_hash
        return True
