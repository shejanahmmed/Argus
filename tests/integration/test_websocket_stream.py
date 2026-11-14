"""Integration test for real-time WebSocket telemetry stream."""

from __future__ import annotations

from starlette.testclient import TestClient

from argus.api.app import app
from argus.api.dependencies import get_container


def test_websocket_stream_handshake_and_events() -> None:
    client = TestClient(app)
    container = get_container()
    container.reset()

    with client.websocket_connect("/ws/v1/stream?tenant_id=t1&workspace_id=w1") as websocket:
        # 1. Handshake frame
        welcome = websocket.receive_json()
        assert welcome["topic"] == "system.connected"
        assert welcome["payload"]["status"] == "ONLINE"

        # 2. Ping-pong
        websocket.send_text("ping")
        pong = websocket.receive_json()
        assert pong["topic"] == "system.pong"

        # 3. Trigger an event on a named channel and verify wildcard fan-out over WebSocket
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
