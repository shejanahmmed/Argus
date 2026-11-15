"""Integration test for system checkpoint endpoint and dashboard readiness metadata."""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from argus.api.app import app
from argus.api.dependencies import get_container
from argus.core.config import ArgusSettings


def test_system_checkpoint_sqlite_and_memory(tmp_path: Path) -> None:
    client = TestClient(app)
    container = get_container()
    db_file = tmp_path / "sys_test.db"

    old_backend = container._backend
    old_engine = container._sqlite_engine
    old_settings = container.settings

    try:
        # 1. Test SQLite mode checkpointing
        container.settings = ArgusSettings(storage_backend="sqlite", db_path=str(db_file))
        container._backend = "sqlite"
        container._db_path = str(db_file)
        container._init_stores()

        res = client.post("/api/v1/system/checkpoint?mode=PASSIVE")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "CHECKPOINTED"
        assert data["busy"] == 0
        assert "log_frames" in data
        assert "checkpointed_frames" in data

        # 2. Test in-memory mode skipped response
        container.settings = ArgusSettings(storage_backend="memory")
        container._backend = "memory"
        container._sqlite_engine = None
        container._init_stores()

        res_mem = client.post("/api/v1/system/checkpoint")
        assert res_mem.status_code == 200
        data_mem = res_mem.json()
        assert data_mem["status"] == "SKIPPED"
        assert data_mem["reason"] == "In-memory backend active"
    finally:
        if container._sqlite_engine is not None:
            container._sqlite_engine.close()
        container.settings = old_settings
        container._backend = old_backend
        container._sqlite_engine = old_engine
        container._init_stores()


def test_readyz_diagnostics_structure() -> None:
    client = TestClient(app)
    res = client.get("/readyz?diagnostics=true")
    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "READY"
    assert "service" in payload
    assert "storage_backend" in payload
    assert "diagnostics" in payload
