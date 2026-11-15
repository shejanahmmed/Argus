"""Real-time WebSocket telemetry and C2 event streaming."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from argus.api.dependencies import get_container
from argus.core.config import ArgusEnvironment
from argus.core.errors import AuthorizationError
from argus.core.ids import utc_now
from argus.core.tenancy import Role, TenantContext

router = APIRouter(prefix="/ws/v1", tags=["Stream"])


@router.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    token: Annotated[str | None, Query()] = None,
    tenant_id: Annotated[str, Query()] = "dev_tenant",
    workspace_id: Annotated[str, Query()] = "dev_workspace",
    actor_id: Annotated[str, Query()] = "operator_ws",
    channels: Annotated[str, Query()] = "*",
) -> None:
    """Real-time pub/sub stream delivering span ingestions, loop alerts, and C2 events."""
    container = get_container()
    ctx: TenantContext

    if token:
        try:
            ctx = container.authenticator.verify_token(token)
        except AuthorizationError:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid or expired bearer token",
            )
            return
    elif container.settings.env in (ArgusEnvironment.DEVELOPMENT, ArgusEnvironment.TESTING):
        ctx = TenantContext(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            role=Role.OPERATOR,
        )
    else:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Authentication required: Provide token query parameter.",
        )
        return

    await websocket.accept()

    initial_channels = [c.strip() for c in channels.split(",") if c.strip()]
    active_patterns: set[str] = set(initial_channels) if initial_channels else {"*"}

    # Initial connection acknowledgment
    await websocket.send_text(
        json.dumps(
            {
                "topic": "system.connected",
                "payload": {
                    "status": "ONLINE",
                    "tenant_id": ctx.tenant_id,
                    "workspace_id": ctx.workspace_id,
                    "stream": "Argus C2 Real-Time EventBus",
                    "channels": sorted(active_patterns),
                    "timestamp": utc_now().isoformat(),
                },
            }
        )
    )

    subscription = container.event_bus.subscribe(ctx, patterns_set=active_patterns)

    async def _send_events() -> None:
        async for event in subscription:
            await websocket.send_text(json.dumps(event))

    async def _receive_client() -> None:
        while True:
            data = await websocket.receive_text()
            stripped = data.strip()
            if stripped == "ping":
                await websocket.send_text(
                    json.dumps({"topic": "system.pong", "timestamp": utc_now().isoformat()})
                )
                continue

            try:
                msg = json.loads(data)
            except Exception:
                continue

            if not isinstance(msg, dict):
                continue

            action = msg.get("action")
            if action == "ping":
                await websocket.send_text(
                    json.dumps({"topic": "system.pong", "timestamp": utc_now().isoformat()})
                )
            elif action == "subscribe":
                new_chans = msg.get("channels", [])
                if isinstance(new_chans, list):
                    for ch in new_chans:
                        if isinstance(ch, str) and ch.strip():
                            active_patterns.add(ch.strip())
                await websocket.send_text(
                    json.dumps(
                        {
                            "topic": "system.subscribed",
                            "channels": sorted(active_patterns),
                        }
                    )
                )
            elif action == "unsubscribe":
                rem_chans = msg.get("channels", [])
                if isinstance(rem_chans, list):
                    for ch in rem_chans:
                        active_patterns.discard(str(ch).strip())
                await websocket.send_text(
                    json.dumps(
                        {
                            "topic": "system.unsubscribed",
                            "channels": sorted(active_patterns),
                        }
                    )
                )

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
