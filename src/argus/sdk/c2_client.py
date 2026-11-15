"""Runtime Command & Control (C2) client SDK for autonomous agent workers.

Allows distributed agent workers to register sessions, checkpoint memory state,
evaluate pre-execution MCP tool calls against the Argus Control Plane, and sync spans.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import httpx

from argus.c2.lease_manager import HeartbeatStatus, LeaseSummary
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    ArgusSpan,
    AuditLogResponse,
    AuditQueryResponse,
    AuditVerificationResult,
    CheckpointRecord,
    CircuitBreakerVerdict,
    DowngradeRecommendation,
    FleetROISummary,
    ModelBenchmarkProfile,
    PendingToolCall,
    SessionDowngradeReport,
    TrajectoryEvaluationReport,
    WorkflowROIAttribution,
)
from argus.core.tenancy import TenantContext


class ArgusC2Client:
    """Async HTTP client connecting an agent runtime to the Argus Control Plane."""

    def __init__(
        self,
        ctx: TenantContext,
        *,
        auth_token: str | None = None,
        base_url: str = "http://localhost:8000",
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._ctx = ctx
        self._auth_token = auth_token
        self._base_url = base_url.rstrip("/")
        self._external_client = client
        self._timeout = timeout_seconds

    @property
    def headers(self) -> dict[str, str]:
        """Standard multi-tenant RBAC headers for Argus Control Plane requests."""
        h = {
            "X-Tenant-ID": self._ctx.tenant_id,
            "X-Workspace-ID": self._ctx.workspace_id,
            "X-Actor-ID": self._ctx.actor_id,
            "X-Role": self._ctx.role.value,
        }
        if self._auth_token:
            h["Authorization"] = f"Bearer {self._auth_token}"
        return h

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

    async def sync_spans(self, spans: Sequence[ArgusSpan]) -> dict[str, Any]:
        """Synchronize a batch of telemetry spans with the Control Plane."""
        return await self.ingest_spans(spans)

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

    async def release_lease(
        self,
        *,
        session_id: uuid.UUID,
        worker_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Voluntarily release a worker lease upon graceful agent shutdown."""
        data: dict[str, Any] = await self._request(
            "POST",
            f"/api/v1/c2/{session_id}/release-lease",
            json_body={"worker_id": worker_id, "reason": reason},
        )
        return data

    async def get_lease(self, session_id: uuid.UUID) -> LeaseSummary | None:
        """Inspect the active worker lease for an autonomous agent session."""
        try:
            data = await self._request("GET", f"/api/v1/c2/{session_id}/lease")
            return LeaseSummary.model_validate(data)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def list_leases(self, *, active_only: bool = True) -> list[LeaseSummary]:
        """List active or all worker leases within the tenant workspace."""
        path = f"/api/v1/c2/leases?active_only={'true' if active_only else 'false'}"
        data = await self._request("GET", path)
        return [LeaseSummary.model_validate(item) for item in data]

    async def reap_expired_leases(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Trigger the Dead-Man's Switch reaper sweep for expired leases."""
        path = f"/api/v1/c2/leases/reap?dry_run={'true' if dry_run else 'false'}"
        data: dict[str, Any] = await self._request("POST", path)
        return data

    async def get_audit_log(self, session_id: uuid.UUID) -> AuditLogResponse:
        """Fetch the compliance audit log for a session with cryptographic verification."""
        data = await self._request("GET", f"/api/v1/c2/{session_id}/audit-log")
        return AuditLogResponse.model_validate(data)

    async def verify_audit_log(self, session_id: uuid.UUID) -> AuditVerificationResult:
        """Run cryptographic verification across the audit chain and return the report."""
        data = await self._request("GET", f"/api/v1/c2/{session_id}/audit-log/verify")
        return AuditVerificationResult.model_validate(data)

    async def query_audit_entries(
        self,
        *,
        session_id: uuid.UUID | None = None,
        event_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditQueryResponse:
        """Query audit log entries across the workspace/tenant with optional filters."""
        params: list[str] = [f"limit={limit}", f"offset={offset}"]
        if session_id is not None:
            params.append(f"session_id={session_id}")
        if event_type is not None:
            params.append(f"event_type={event_type}")
        if actor_id is not None:
            params.append(f"actor_id={actor_id}")
        query_str = "&".join(params)
        data = await self._request("GET", f"/api/v1/c2/audit-log?{query_str}")
        return AuditQueryResponse.model_validate(data)

    async def get_session_roi(
        self,
        session_id: uuid.UUID,
        *,
        workflow_id: str = "wf_default",
        assigned_business_value_usd: float = 100.0,
        task_completed: bool | None = None,
        infra_cost_usd: float | None = None,
        c2_intervention_cost_usd: float | None = None,
    ) -> WorkflowROIAttribution:
        """Calculate token attribution, 4-bucket costs, and net ROI for a session."""
        params: list[str] = [
            f"workflow_id={workflow_id}",
            f"assigned_business_value_usd={assigned_business_value_usd}",
        ]
        if task_completed is not None:
            params.append(f"task_completed={'true' if task_completed else 'false'}")
        if infra_cost_usd is not None:
            params.append(f"infra_cost_usd={infra_cost_usd}")
        if c2_intervention_cost_usd is not None:
            params.append(f"c2_intervention_cost_usd={c2_intervention_cost_usd}")

        path = f"/api/v1/attribution/roi/{session_id}?{'&'.join(params)}"
        data = await self._request("GET", path)
        return WorkflowROIAttribution.model_validate(data)

    async def evaluate_trajectory(
        self,
        session_id: uuid.UUID,
        *,
        expected_tools: list[str] | None = None,
        goal_keywords: list[str] | None = None,
    ) -> TrajectoryEvaluationReport:
        """Execute deterministic trajectory evaluation analyzing tools, keywords, and goals."""
        payload = {
            "expected_tools": expected_tools or [],
            "goal_keywords": goal_keywords or [],
        }
        data = await self._request(
            "POST", f"/api/v1/attribution/evaluate/{session_id}", json_body=payload
        )
        return TrajectoryEvaluationReport.model_validate(data)

    async def get_fleet_roi(
        self,
        *,
        default_task_value_usd: float = 100.0,
    ) -> FleetROISummary:
        """Retrieve aggregated fleet-wide ROI attribution, spend, and performance statistics."""
        path = f"/api/v1/attribution/fleet-roi?default_task_value_usd={default_task_value_usd}"
        data = await self._request("GET", path)
        return FleetROISummary.model_validate(data)

    async def get_benchmark_catalog(self) -> list[ModelBenchmarkProfile]:
        """Retrieve full Hugging Face Open LLM and GAIA benchmark model profiles."""
        data = await self._request("GET", "/api/v1/attribution/benchmarks/catalog")
        return [ModelBenchmarkProfile.model_validate(item) for item in data]

    async def register_benchmark_model(
        self, profile: ModelBenchmarkProfile
    ) -> ModelBenchmarkProfile:
        """Register or update a custom model benchmark profile in the catalog."""
        data = await self._request(
            "POST",
            "/api/v1/attribution/benchmarks/catalog",
            json_body=profile.model_dump(mode="json"),
        )
        return ModelBenchmarkProfile.model_validate(data)

    async def recommend_model_downgrade(
        self,
        current_model: str,
        *,
        min_acceptable_accuracy: float = 0.50,
        open_weights_only: bool = False,
    ) -> list[DowngradeRecommendation]:
        """Query Pareto-optimal model substitution recommendations."""
        payload = {
            "current_model": current_model,
            "min_acceptable_accuracy": min_acceptable_accuracy,
            "open_weights_only": open_weights_only,
        }
        data = await self._request(
            "POST", "/api/v1/attribution/benchmarks/recommend", json_body=payload
        )
        return [DowngradeRecommendation.model_validate(item) for item in data]

    async def recommend_session_downgrade(
        self,
        session_id: uuid.UUID,
        *,
        min_acceptable_accuracy: float = 0.50,
        open_weights_only: bool = False,
        annual_session_volume: int = 10000,
    ) -> SessionDowngradeReport:
        """Analyze session spans and project dollar savings from model substitutions."""
        payload = {
            "min_acceptable_accuracy": min_acceptable_accuracy,
            "open_weights_only": open_weights_only,
            "annual_session_volume": annual_session_volume,
        }
        data = await self._request(
            "POST",
            f"/api/v1/attribution/benchmarks/recommend-session/{session_id}",
            json_body=payload,
        )
        return SessionDowngradeReport.model_validate(data)
