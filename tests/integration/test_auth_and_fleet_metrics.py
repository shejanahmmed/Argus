"""Integration tests for Token Management API, Production Zero-Trust Auth, and Fleet Metrics."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from argus.api.app import app
from argus.api.dependencies import get_container
from argus.core.config import ArgusEnvironment, ArgusSettings
from argus.core.tenancy import Role, TenantContext
from argus.security.auth import HmacTokenAuthenticator


@pytest.fixture(autouse=True)
def reset_app_state() -> None:
    """Ensure clean container state before each test."""
    container = get_container()
    container.settings = ArgusSettings(env=ArgusEnvironment.DEVELOPMENT)
    container.reset()


@pytest.mark.asyncio
async def test_auth_token_issuance_and_me_endpoint() -> None:
    container = get_container()
    admin_ctx = TenantContext(
        tenant_id="acme_corp",
        workspace_id="prod_eu",
        actor_id="admin_user",
        role=Role.ADMIN,
    )
    admin_token = container.authenticator.issue_token(admin_ctx)

    operator_ctx = TenantContext(
        tenant_id="acme_corp",
        workspace_id="prod_eu",
        actor_id="operator_user",
        role=Role.OPERATOR,
    )
    operator_token = container.authenticator.issue_token(operator_ctx)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. Admin issues a new worker token
        issue_resp = await client.post(
            "/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "tenant_id": "acme_corp",
                "workspace_id": "prod_eu",
                "actor_id": "worker_agent_01",
                "role": "INGESTOR",
                "ttl_seconds": 7200,
            },
        )
        assert issue_resp.status_code == 201
        data = issue_resp.json()
        assert "token" in data
        assert data["actor_id"] == "worker_agent_01"
        assert data["role"] == "INGESTOR"

        new_worker_token = data["token"]

        # 2. Worker verifies identity via /api/v1/auth/me
        me_resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {new_worker_token}"},
        )
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["tenant_id"] == "acme_corp"
        assert me_data["workspace_id"] == "prod_eu"
        assert me_data["actor_id"] == "worker_agent_01"
        assert me_data["role"] == "INGESTOR"

        # 3. Operator lacks ADMIN role -> cannot issue tokens
        forbidden_resp = await client.post(
            "/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {operator_token}"},
            json={
                "tenant_id": "acme_corp",
                "workspace_id": "prod_eu",
                "actor_id": "malicious_actor",
                "role": "ADMIN",
            },
        )
        assert forbidden_resp.status_code == 403

        # 4. Admin cannot issue tokens for foreign tenant
        cross_tenant_resp = await client.post(
            "/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "tenant_id": "foreign_corp",
                "workspace_id": "foreign_ws",
                "actor_id": "foreign_actor",
                "role": "OPERATOR",
            },
        )
        assert cross_tenant_resp.status_code == 403


@pytest.mark.asyncio
async def test_production_zero_trust_unauthenticated_rejection() -> None:
    container = get_container()
    prod_secret = "ultra-secure-production-secret-key-32-chars-2026!"
    container.settings = ArgusSettings(
        env=ArgusEnvironment.PRODUCTION,
        auth_secret=prod_secret,
        allow_anonymous=False,
    )
    container.authenticator = HmacTokenAuthenticator(secret_key=prod_secret)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # 1. Unauthenticated request in production must return 401
        unauth_resp = await client.get("/api/v1/telemetry/sessions")
        assert unauth_resp.status_code == 401
        assert "WWW-Authenticate" in unauth_resp.headers

        # 2. Malformed token must return 401
        bad_token_resp = await client.get(
            "/api/v1/telemetry/sessions",
            headers={"Authorization": "Bearer invalid.token.signature"},
        )
        assert bad_token_resp.status_code == 401

        # 3. Valid Bearer token succeeds
        valid_ctx = TenantContext(
            tenant_id="prod_tenant",
            workspace_id="prod_ws",
            actor_id="prod_admin",
            role=Role.ADMIN,
        )
        valid_token = container.authenticator.issue_token(valid_ctx)
        ok_resp = await client.get(
            "/api/v1/telemetry/sessions",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert ok_resp.status_code == 200
        assert ok_resp.json() == []


@pytest.mark.asyncio
async def test_metrics_aggregates_across_multiple_tenants() -> None:
    container = get_container()
    ctx_a = TenantContext(
        tenant_id="tenant_alpha", workspace_id="ws_a", actor_id="a1", role=Role.ADMIN
    )
    ctx_b = TenantContext(
        tenant_id="tenant_beta", workspace_id="ws_b", actor_id="b1", role=Role.ADMIN
    )

    token_a = container.authenticator.issue_token(ctx_a)
    token_b = container.authenticator.issue_token(ctx_b)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Create session in tenant Alpha
        await client.post(
            "/api/v1/telemetry/sessions",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "workflow_id": "wf_alpha",
                "agent_name": "agent_alpha",
                "framework": "langgraph",
            },
        )

        # Create session in tenant Beta
        await client.post(
            "/api/v1/telemetry/sessions",
            headers={"Authorization": f"Bearer {token_b}"},
            json={
                "workflow_id": "wf_beta",
                "agent_name": "agent_beta",
                "framework": "crewai",
            },
        )

        # Scrape /metrics: should aggregate both sessions (total: 2)
        metrics_resp = await client.get("/metrics")
        assert metrics_resp.status_code == 200
        assert "argus_sessions_total 2" in metrics_resp.text
        assert "argus_sessions_running 2" in metrics_resp.text
