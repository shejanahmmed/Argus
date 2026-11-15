"""Remote HTTP implementation of the TraceStore repository port."""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from typing import Any

import httpx

from argus.core.errors import ArgusError, EntityNotFoundError
from argus.core.schemas import ArgusSpan
from argus.core.tenancy import TenantContext


class HttpTraceStore:
    """Async HTTP transport implementation of the TraceStore port for distributed agents."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        auth_token: str | None = None,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        resolved_url = (
            base_url
            if base_url is not None
            else os.environ.get("ARGUS_BASE_URL", "http://localhost:8000")
        )
        resolved_token = (
            auth_token
            if auth_token is not None
            else os.environ.get("ARGUS_AUTH_TOKEN")
        )
        self._base_url = resolved_url.rstrip("/")
        self._auth_token = resolved_token
        self._timeout = timeout_seconds
        self._external_client = client

    def _headers(self, ctx: TenantContext) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": ctx.tenant_id,
            "X-Workspace-ID": ctx.workspace_id,
            "X-Actor-ID": ctx.actor_id,
            "X-Role": ctx.role.value,
        }
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(timeout=self._timeout)

    async def append_spans(
        self,
        ctx: TenantContext,
        spans: Sequence[ArgusSpan],
    ) -> int:
        """Ship a batch of spans over HTTP to the Argus Control Plane."""
        if not spans:
            return 0

        payload = {"spans": [s.model_dump(mode="json") for s in spans]}
        url = f"{self._base_url}/api/v1/telemetry/spans"
        headers = self._headers(ctx)

        client = await self._get_client()
        try:
            if self._external_client is not None:
                resp = await client.post(url, json=payload, headers=headers)
            else:
                async with client:
                    resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code >= 400:
                raise ArgusError(f"HTTP Trace Ingestion Error ({resp.status_code}): {resp.text}")

            data: dict[str, Any] = resp.json()
            count = data.get("ingested_count", len(spans))
            return int(count)
        except Exception as err:
            if isinstance(err, ArgusError):
                raise
            raise ArgusError(f"Failed to connect to Argus Control Plane at {url}: {err}") from err

    async def get_session_spans(
        self,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> list[ArgusSpan]:
        """Fetch chronological spans for a session over HTTP."""
        url = f"{self._base_url}/api/v1/telemetry/sessions/{session_id}/spans"
        headers = self._headers(ctx)

        client = await self._get_client()
        try:
            if self._external_client is not None:
                resp = await client.get(url, headers=headers)
            else:
                async with client:
                    resp = await client.get(url, headers=headers)

            if resp.status_code == 404:
                raise EntityNotFoundError("AgentSession", str(session_id))
            if resp.status_code >= 400:
                raise ArgusError(f"HTTP Trace Query Error ({resp.status_code}): {resp.text}")

            raw_list: list[dict[str, Any]] = resp.json()
            return [ArgusSpan.model_validate(item) for item in raw_list]
        except Exception as err:
            if isinstance(err, (ArgusError, EntityNotFoundError)):
                raise
            raise ArgusError(f"Failed to query session spans from {url}: {err}") from err

    async def get_trace_subtree(
        self,
        ctx: TenantContext,
        root_dotted_order: str,
    ) -> list[ArgusSpan]:
        """Fetch a dotted-order trace subtree over HTTP."""
        url = f"{self._base_url}/api/v1/telemetry/traces/{root_dotted_order}"
        headers = self._headers(ctx)

        client = await self._get_client()
        try:
            if self._external_client is not None:
                resp = await client.get(url, headers=headers)
            else:
                async with client:
                    resp = await client.get(url, headers=headers)

            if resp.status_code >= 400:
                raise ArgusError(f"HTTP Trace Subtree Error ({resp.status_code}): {resp.text}")

            raw_list: list[dict[str, Any]] = resp.json()
            return [ArgusSpan.model_validate(item) for item in raw_list]
        except Exception as err:
            if isinstance(err, ArgusError):
                raise
            raise ArgusError(f"Failed to query trace subtree from {url}: {err}") from err
