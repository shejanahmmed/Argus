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
    AuditVerificationResult,
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
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row

        # Configure WAL pragmas, normal synchronous writes, foreign keys, and 5s busy timeout
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

        row = self._conn.execute("PRAGMA journal_mode").fetchone()
        self._active_journal_mode = str(row[0]).lower() if row else "unknown"

        self._conn.executescript(_SCHEMA_DDL)
        self._conn.commit()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def active_journal_mode(self) -> str:
        """Active SQLite journal mode (e.g. 'wal' for disk files, 'memory' for in-memory)."""
        return self._active_journal_mode

    def ping(self) -> bool:
        """Verify underlying SQLite database connection is responsive."""
        try:
            self._conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def checkpoint_wal(self, mode: str = "PASSIVE") -> tuple[int, int, int]:
        """Flush WAL frames to main database file.

        Args:
            mode: Checkpoint mode ('PASSIVE', 'FULL', 'RESTART', or 'TRUNCATE').

        Returns:
            Tuple of (busy, log_frames, checkpointed_frames).
        """
        valid_modes = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}
        target_mode = mode.upper()
        if target_mode not in valid_modes:
            raise ValueError(
                f"Invalid WAL checkpoint mode '{mode}'. Must be one of {sorted(valid_modes)}"
            )
        cur = self._conn.execute(f"PRAGMA wal_checkpoint({target_mode})")
        row = cur.fetchone()
        if row is not None:
            return (int(row[0]), int(row[1]), int(row[2]))
        return (0, 0, 0)

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic metrics including WAL status, page size, and table row counts."""
        integrity_row = self._conn.execute("PRAGMA integrity_check(1)").fetchone()
        integrity_status = str(integrity_row[0]) if integrity_row else "unknown"

        journal_row = self._conn.execute("PRAGMA journal_mode").fetchone()
        journal_mode = str(journal_row[0]).lower() if journal_row else self._active_journal_mode

        page_size_row = self._conn.execute("PRAGMA page_size").fetchone()
        page_size = int(page_size_row[0]) if page_size_row else 4096

        page_count_row = self._conn.execute("PRAGMA page_count").fetchone()
        page_count = int(page_count_row[0]) if page_count_row else 0

        freelist_row = self._conn.execute("PRAGMA freelist_count").fetchone()
        freelist_count = int(freelist_row[0]) if freelist_row else 0

        file_size_bytes = 0
        wal_size_bytes = 0
        if self._db_path != ":memory:":
            db_file = Path(self._db_path)
            if db_file.exists():
                file_size_bytes = db_file.stat().st_size
            wal_file = Path(f"{self._db_path}-wal")
            if wal_file.exists():
                wal_size_bytes = wal_file.stat().st_size

        # Table row counts
        table_names = [
            "argus_sessions",
            "argus_checkpoints",
            "argus_spans",
            "argus_budgets",
            "argus_audit_ledger",
        ]
        table_counts: dict[str, int] = {}
        for table in table_names:
            try:
                cnt_row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                table_counts[table] = int(cnt_row[0]) if cnt_row else 0
            except Exception:
                table_counts[table] = 0

        return {
            "db_path": self._db_path,
            "journal_mode": journal_mode,
            "page_size": page_size,
            "page_count": page_count,
            "freelist_count": freelist_count,
            "database_size_bytes": file_size_bytes,
            "wal_size_bytes": wal_size_bytes,
            "total_size_bytes": file_size_bytes + wal_size_bytes,
            "integrity_check": integrity_status,
            "table_counts": {
                "sessions": table_counts.get("argus_sessions", 0),
                "checkpoints": table_counts.get("argus_checkpoints", 0),
                "spans": table_counts.get("argus_spans", 0),
                "budgets": table_counts.get("argus_budgets", 0),
                "audit_entries": table_counts.get("argus_audit_ledger", 0),
            },
        }

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

    async def list_checkpoints(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[CheckpointRecord]:
        async with self._engine.lock:
            session = self._get_session_sync(session_id)
            if session is None:
                raise EntityNotFoundError("AgentSession", str(session_id))
            ctx.assert_same_tenant(session.tenant_id, session.workspace_id)

            cur = self._engine.conn.execute(
                """
                SELECT payload_json FROM argus_checkpoints
                WHERE session_id = ?
                ORDER BY seq_id ASC
                """,
                (str(session_id),),
            )
            rows = cur.fetchall()
            return [CheckpointRecord.model_validate_json(r["payload_json"]) for r in rows]

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

    async def list_all_sessions_fleet(self) -> list[AgentSession]:
        async with self._engine.lock:
            cur = self._engine.conn.execute(
                "SELECT payload_json FROM argus_sessions"
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

    async def release_budget(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
        amount_usd: float,
    ) -> float:
        if amount_usd < 0.0:
            raise ValueError("amount_usd cannot be negative.")

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
            updated = max(0.0, round(current - amount_usd, 8))
            self._engine.conn.execute(
                """
                INSERT INTO argus_budgets (tenant_id, workspace_id, session_id, accumulated_usd)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, workspace_id, session_id)
                DO UPDATE SET accumulated_usd = excluded.accumulated_usd
                """,
                (ctx.tenant_id, ctx.workspace_id, str(session_id), updated),
            )
            self._engine.conn.commit()
            return updated

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
        report = await self.verify_session_chain_detailed(ctx, session_id)
        return report.is_valid

    async def verify_session_chain_detailed(
        self, ctx: TenantContext, session_id: uuid.UUID
    ) -> AuditVerificationResult:
        """Verify chain from genesis to tip, identifying exact block index and violation."""
        entries = await self.get_session_audit_log(ctx, session_id)
        expected_prev = GENESIS_AUDIT_HASH
        tip_hash = entries[-1].entry_hash if entries else None

        for idx, entry in enumerate(entries):
            valid, violation_type, violation_details = entry.check_integrity_detailed(
                expected_prev
            )
            if not valid:
                return AuditVerificationResult(
                    session_id=session_id,
                    is_valid=False,
                    total_entries=len(entries),
                    genesis_hash=GENESIS_AUDIT_HASH,
                    tip_hash=tip_hash,
                    tampered_entry_index=idx,
                    tampered_audit_id=entry.audit_id,
                    violation_type=violation_type,
                    violation_details=violation_details,
                )
            expected_prev = entry.entry_hash

        return AuditVerificationResult(
            session_id=session_id,
            is_valid=True,
            total_entries=len(entries),
            genesis_hash=GENESIS_AUDIT_HASH,
            tip_hash=tip_hash,
        )

    async def query_audit_entries(
        self,
        ctx: TenantContext,
        *,
        session_id: uuid.UUID | None = None,
        event_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditLogEntry], int]:
        """Query audit entries across workspace/tenant with optional filters and pagination."""
        conditions = ["tenant_id = ?", "workspace_id = ?"]
        params: list[Any] = [ctx.tenant_id, ctx.workspace_id]
        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(str(session_id))
        where_clause = " AND ".join(conditions)

        async with self._engine.lock:
            cur = self._engine.conn.execute(
                f"""
                SELECT payload_json FROM argus_audit_ledger
                WHERE {where_clause}
                ORDER BY seq_id ASC
                """,
                params,
            )
            rows = cur.fetchall()

        entries = [AuditLogEntry.model_validate_json(row["payload_json"]) for row in rows]
        if event_type is not None:
            entries = [e for e in entries if e.event_type == event_type]
        if actor_id is not None:
            entries = [e for e in entries if e.actor_id == actor_id]

        total = len(entries)
        paged = entries[offset : offset + limit]
        return paged, total
