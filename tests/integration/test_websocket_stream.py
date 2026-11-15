"""Integration test for real-time WebSocket telemetry stream."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from argus.api.app import app
from argus.api.dependencies import get_container
from argus.core.config import ArgusEnvironment, ArgusSettings
from argus.core.tenancy import Role, TenantContext
from argus.security.auth import HmacTokenAuthenticator


def test_websocket_stream_handshake_and_events() -> None:
    client = TestClient(app)
    container = get_container()
    container.reset()

    with client.websocket_connect("/ws/v1/stream?tenant_id=t1&workspace_id=w1") as websocket:
        # 1. Handshake frame
        welcome = websocket.receive_json()
        assert welcome["topic"] == "system.connected"
        assert welcome["payload"]["status"] == "ONLINE"
        assert welcome["payload"]["channels"] == ["*"]

        # 2. Ping-pong (raw string)
        websocket.send_text("ping")
        pong = websocket.receive_json()
        assert pong["topic"] == "system.pong"

        # 3. Ping-pong (JSON control frame)
        websocket.send_text(json.dumps({"action": "ping"}))
        pong_json = websocket.receive_json()
        assert pong_json["topic"] == "system.pong"

        # 4. Trigger an event on a named channel and verify wildcard fan-out over WebSocket
        res = client.post(
            "/api/v1/telemetry/sessions",
            headers={
                "X-Tenant-ID": "t1",
                "X-Workspace-ID": "w1",
                "X-Actor-ID": "tester",
                "X-Role": "ADMIN",
            },
            json={
                "workflow_id": "ws_test_wf",
                "agent_name": "ws_agent",
                "framework": "langgraph",
                "budget_cap_usd": 10.0,
            },
        )
        assert res.status_code == 200
        event_frame = websocket.receive_json()
        assert event_frame["channel"] == "telemetry.sessions"
        assert event_frame["agent_name"] == "ws_agent"


def test_websocket_dynamic_channel_subscription() -> None:
    client = TestClient(app)
    container = get_container()
    container.reset()

    with client.websocket_connect(
        "/ws/v1/stream?tenant_id=t1&workspace_id=w1&channels=c2.*"
    ) as websocket:
        # 1. Initial Handshake with c2.* channel
        welcome = websocket.receive_json()
        assert welcome["topic"] == "system.connected"
        assert welcome["payload"]["channels"] == ["c2.*"]

        # 2. Dynamic Subscribe to governance.*
        websocket.send_text(json.dumps({"action": "subscribe", "channels": ["governance.*"]}))
        sub_resp = websocket.receive_json()
        assert sub_resp["topic"] == "system.subscribed"
        assert sub_resp["channels"] == ["c2.*", "governance.*"]

        # 3. Dynamic Unsubscribe from c2.*
        websocket.send_text(json.dumps({"action": "unsubscribe", "channels": ["c2.*"]}))
        unsub_resp = websocket.receive_json()
        assert unsub_resp["topic"] == "system.unsubscribed"
        assert unsub_resp["channels"] == ["governance.*"]


def test_websocket_unauthenticated_rejection_in_production() -> None:
    client = TestClient(app)
    container = get_container()
    container.reset()

    prod_secret = "ultra-secure-production-secret-key-32-chars-2026!"
    old_settings = container.settings
    old_auth = container.authenticator
    try:
        container.settings = ArgusSettings(
            env=ArgusEnvironment.PRODUCTION,
            auth_secret=prod_secret,
            allow_anonymous=False,
        )
        container.authenticator = HmacTokenAuthenticator(secret_key=prod_secret)

        # Connecting without token must be rejected with 1008 policy violation
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect("/ws/v1/stream?tenant_id=t1&workspace_id=w1"),
        ):
            pass
        assert exc_info.value.code == 1008

        # Connecting with valid bearer token succeeds
        prod_ctx = TenantContext(
            tenant_id="prod_tenant",
            workspace_id="prod_ws",
            actor_id="prod_admin",
            role=Role.ADMIN,
        )
        token = container.authenticator.issue_token(prod_ctx)
        with client.websocket_connect(
            f"/ws/v1/stream?token={token}&tenant_id=prod_tenant&workspace_id=prod_ws"
        ) as websocket:
            welcome = websocket.receive_json()
            assert welcome["topic"] == "system.connected"
            assert welcome["payload"]["status"] == "ONLINE"
    finally:
        container.settings = old_settings
        container.authenticator = old_auth
