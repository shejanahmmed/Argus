"""Real-time WebSocket telemetry and C2 event streaming."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from argus.api.dependencies import get_container
from argus.core.tenancy import Role, TenantContext

router = APIRouter(prefix="/ws/v1", tags=["Stream"])


@router.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    tenant_id: str = Query(default="default_tenant"),
    workspace_id: str = Query(default="default_workspace"),
    actor_id: str = Query(default="operator_ws"),
) -> None:
    """Real-time pub/sub stream delivering span ingestions, loop alerts, and C2 events."""
    await websocket.accept()
    container = get_container()

    ctx = TenantContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        role=Role.OPERATOR,
    )

    # Initial connection acknowledgment
    await websocket.send_text(
        json.dumps(
            {
                "topic": "system.connected",
                "payload": {
                    "status": "ONLINE",
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "stream": "Argus C2 Real-Time EventBus",
                },
            }
        )
    )

    subscription = container.event_bus.subscribe(ctx, channel="*")

    async def _send_events() -> None:
        async for event in subscription:
            await websocket.send_text(json.dumps(event))

    async def _receive_client() -> None:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"topic": "system.pong"}))

    send_task = asyncio.create_task(_send_events())
    recv_task = asyncio.create_task(_receive_client())

    try:
        _done, pending = await asyncio.wait(
            [send_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        send_task.cancel()
        recv_task.cancel()
