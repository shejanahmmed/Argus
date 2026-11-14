"""Runtime Command & Control (C2) client SDK for autonomous agent workers.

Allows distributed agent workers to register sessions, checkpoint memory state,
evaluate pre-execution MCP tool calls against the Argus Control Plane, and sync spans.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import httpx

from argus.c2.lease_manager import HeartbeatStatus
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    ArgusSpan,
    CheckpointRecord,
    CircuitBreakerVerdict,
    PendingToolCall,
)
from argus.core.tenancy import TenantContext


class ArgusC2Client:
    """Async HTTP client connecting an agent runtime to the Argus Control Plane."""

    def __init__(
        self,
        ctx: TenantContext,
        *,
        base_url: str = "http://localhost:8000",
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._ctx = ctx
        self._base_url = base_url.rstrip("/")
        self._external_client = client
        self._timeout = timeout_seconds

    @property
    def headers(self) -> dict[str, str]:
        """Standard multi-tenant RBAC headers for Argus Control Plane requests."""
        return {
            "X-Tenant-ID": self._ctx.tenant_id,
            "X-Workspace-ID": self._ctx.workspace_id,
            "X-Actor-ID": self._ctx.actor_id,
            "X-Role": self._ctx.role.value,
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if self._external_client is not None:
            resp = await self._external_client.request(
                method,
                path,
                headers=self.headers,
                json=json_body,
            )
            resp.raise_for_status()
            return resp.json()

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        ) as client:
            resp = await client.request(
                method,
                path,
                headers=self.headers,
                json=json_body,
            )
            resp.raise_for_status()
            return resp.json()

    async def register_session(
        self,
        *,
        workflow_id: str,
        agent_name: str,
        framework: AgentFramework = AgentFramework.LANGGRAPH,
        budget_cap_usd: float = 50.0,
        session_id: uuid.UUID | None = None,
    ) -> AgentSession:
        """Register a new governed agent session with the Control Plane."""
        payload: dict[str, Any] = {
            "workflow_id": workflow_id,
            "agent_name": agent_name,
            "framework": framework.value,
            "budget_cap_usd": budget_cap_usd,
        }
        if session_id is not None:
            payload["session_id"] = str(session_id)
        data = await self._request("POST", "/api/v1/telemetry/sessions", json_body=payload)
        return AgentSession.model_validate(data)

    async def ingest_spans(self, spans: Sequence[ArgusSpan]) -> dict[str, Any]:
        """Ship a batch of telemetry spans to the Control Plane."""
        payload = {"spans": [s.model_dump(mode="json") for s in spans]}
        res: dict[str, Any] = await self._request(
            "POST", "/api/v1/telemetry/spans", json_body=payload
        )
        return res

    async def save_checkpoint(
        self,
        *,
        session_id: uuid.UUID,
        node_name: str,
        step_index: int,
        memory_state: dict[str, Any],
        expected_parent_checkpoint_id: uuid.UUID | None = None,
    ) -> CheckpointRecord:
        """Persist a versioned checkpoint snapshot with optimistic locking."""
        payload: dict[str, Any] = {
            "node_name": node_name,
            "step_index": step_index,
            "memory_state": memory_state,
            "expected_parent_checkpoint_id": (
                str(expected_parent_checkpoint_id)
                if expected_parent_checkpoint_id is not None
                else None
            ),
        }
        data = await self._request(
            "POST",
            f"/api/v1/c2/{session_id}/checkpoints",
            json_body=payload,
        )
        return CheckpointRecord.model_validate(data)

    async def get_latest_checkpoint(
        self, session_id: uuid.UUID
    ) -> CheckpointRecord | None:
        """Fetch the latest checkpoint state (including any operator RFC 6902 edits)."""
        data = await self._request("GET", f"/api/v1/c2/{session_id}/checkpoints/latest")
        if data is None:
            return None
        return CheckpointRecord.model_validate(data)

    async def intercept_tool_call(
        self,
        *,
        session_id: uuid.UUID,
        tool_call_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        estimated_cost_usd: float = 0.001,
        hard_cap_usd: float = 100.0,
    ) -> tuple[CircuitBreakerVerdict, PendingToolCall | None]:
        """Evaluate an MCP or framework tool call through the pre-execution governance gate."""
        payload: dict[str, Any] = {
            "session_id": str(session_id),
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "estimated_cost_usd": estimated_cost_usd,
            "hard_cap_usd": hard_cap_usd,
        }
        data = await self._request(
            "POST", "/api/v1/governance/mcp/intercept", json_body=payload
        )
        verdict = CircuitBreakerVerdict.model_validate(data["verdict"])
        pending_raw = data.get("pending_tool_call")
        pending = PendingToolCall.model_validate(pending_raw) if pending_raw else None
        return verdict, pending

    async def heartbeat(
        self,
        *,
        session_id: uuid.UUID,
        worker_id: str,
        ttl_seconds: float = 300.0,
    ) -> HeartbeatStatus:
        """Send a distributed worker heartbeat and retrieve C2 control directives."""
        data = await self._request(
            "POST",
            f"/api/v1/c2/{session_id}/heartbeat",
            json_body={"worker_id": worker_id, "ttl_seconds": ttl_seconds},
        )
        return HeartbeatStatus.model_validate(data)
