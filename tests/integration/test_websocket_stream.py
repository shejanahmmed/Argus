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
