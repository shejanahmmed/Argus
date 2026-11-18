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


def test_root_assets_and_browser_redirect() -> None:
    client = TestClient(app)

    # 1. Favicon and brand assets routed at root level
    res_svg = client.get("/argus_logo.svg")
    assert res_svg.status_code == 200
    assert "svg" in res_svg.headers.get("content-type", "").lower()

    res_png = client.get("/argus_logo.png")
    assert res_png.status_code == 200
    assert "png" in res_png.headers.get("content-type", "").lower()

    res_fav = client.get("/favicon.svg")
    assert res_fav.status_code == 200

    # 2. Browser GET / with text/html redirects to /dashboard
    res_browser = client.get(
        "/", headers={"accept": "text/html,application/xhtml+xml"}, follow_redirects=False
    )
    assert res_browser.status_code == 307
    assert res_browser.headers.get("location") == "/dashboard"

    # 3. API client GET / with application/json receives API directory
    res_api = client.get("/", headers={"accept": "application/json"})
    assert res_api.status_code == 200
    data = res_api.json()
    assert data["name"] == "Argus C2 Control Plane API"
    assert "/dashboard" in data["dashboard_url"]


def test_cli_serve_subcommand_parser() -> None:
    from argus.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["serve", "--host", "127.0.0.1", "--port", "9000", "--reload"])
    assert args.subcommand == "serve"
    assert args.host == "127.0.0.1"
    assert args.port == 9000
    assert args.reload is True
    assert args.workers == 1
