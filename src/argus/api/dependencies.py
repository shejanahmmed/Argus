"""Dependency injection providers and container for the Argus Control Plane API."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, Query, status

from argus.adapters_infra.in_memory import (
    InMemoryAuditStore,
    InMemoryBudgetStore,
    InMemoryControlStore,
    InMemoryEventBus,
    InMemoryTraceStore,
)
from argus.adapters_infra.sqlite_store import (
    SqliteAuditStore,
    SqliteBudgetStore,
    SqliteControlStore,
    SqliteEngine,
    SqliteTraceStore,
)
from argus.attribution.evaluator import TrajectoryEvaluator
from argus.attribution.hf_benchmarks import HuggingFaceBenchmarkAnalyzer
from argus.attribution.roi_engine import ROIEngine
from argus.c2.audit_ledger import C2AuditLedger
from argus.c2.lease_manager import C2LeaseManager
from argus.c2.state_manager import C2StateManager
from argus.c2.tool_override import ToolOverrideEngine
from argus.core.config import ArgusEnvironment, ArgusSettings
from argus.core.errors import AuthorizationError
from argus.core.schemas import PendingToolCall, ResolvedToolOverride
from argus.core.tenancy import Role, TenantContext
from argus.governance.budget_guard import BudgetGuard
from argus.governance.loop_detector import LoopDetector
from argus.governance.mcp_proxy import McpGovernanceProxy
from argus.ingestors.cloudwatch_logs import CorrelatedContainerLog
from argus.ingestors.phoenix_bridge import ArizePhoenixBridge
from argus.ports.repositories import (
    AuditStore,
    BudgetStore,
    ControlStore,
    EventBus,
    TraceStore,
)
from argus.security.auth import HmacTokenAuthenticator, parse_w3c_baggage


class AppContainer:
    """Singleton container managing operational state, stores, and engines."""

    def __init__(
        self,
        settings: ArgusSettings | None = None,
        backend: str | None = None,
        db_path: str | None = None,
    ) -> None:
        self.settings = settings or ArgusSettings.from_env()
        self._backend = (backend or self.settings.storage_backend).lower()
        self._db_path = db_path or self.settings.db_path
        self._sqlite_engine: SqliteEngine | None = None
        self.authenticator = HmacTokenAuthenticator(settings=self.settings)

        # Pending intercepted tool calls: tenant:session -> list[PendingToolCall]
        self.pending_tool_calls: dict[str, list[PendingToolCall]] = {}
        # Resolved tool overrides: tenant:session:call_id -> ResolvedToolOverride
        self.resolved_overrides: dict[str, ResolvedToolOverride] = {}
        # Recent correlated container logs ring buffer
        self.container_logs: list[CorrelatedContainerLog] = []

        self._init_stores()

    def _init_stores(self) -> None:
        if self._backend == "sqlite":
            if self._sqlite_engine is None:
                self._sqlite_engine = SqliteEngine(self._db_path)
            else:
                self._sqlite_engine.reset_tables()
            self.trace_store: TraceStore = SqliteTraceStore(self._sqlite_engine)
            self.control_store: ControlStore = SqliteControlStore(self._sqlite_engine)
            self.budget_store: BudgetStore = SqliteBudgetStore(self._sqlite_engine)
            self.audit_store: AuditStore = SqliteAuditStore(self._sqlite_engine)
        else:
            self.trace_store = InMemoryTraceStore()
            self.control_store = InMemoryControlStore()
            self.budget_store = InMemoryBudgetStore()
            self.audit_store = InMemoryAuditStore()

        self.event_bus: EventBus = InMemoryEventBus(
            max_queue_size=self.settings.event_bus_queue_max_size
        )
        self.audit_ledger = C2AuditLedger(audit_store=self.audit_store)
        self.loop_detector = LoopDetector(
            window_size=self.settings.loop_window_size,
            max_exact_repetitions=self.settings.loop_exact_threshold,
            max_oscillations=self.settings.loop_oscillation_threshold,
            semantic_threshold=self.settings.loop_semantic_threshold,
            simhash_max_hamming=self.settings.loop_simhash_max_hamming,
            max_tracked_sessions=self.settings.loop_max_tracked_sessions,
        )
        self.budget_guard = BudgetGuard(
            backend=self.budget_store,
            warning_threshold=self.settings.budget_warning_threshold,
        )
        self.mcp_proxy = McpGovernanceProxy(
            loop_detector=self.loop_detector,
            budget_guard=self.budget_guard,
            extra_destructive_patterns=self.settings.mcp_extra_destructive_patterns,
            enforce_injection_scan=self.settings.mcp_enforce_injection_scan,
        )
        self.c2_state_manager = C2StateManager(control_store=self.control_store)
        self.lease_manager = C2LeaseManager(
            control_store=self.control_store,
            audit_store=self.audit_store,
            event_bus=self.event_bus,
            min_ttl_seconds=self.settings.lease_min_ttl_seconds,
            max_ttl_seconds=self.settings.lease_max_ttl_seconds,
        )
        self.tool_override_engine = ToolOverrideEngine()
        self.trajectory_evaluator = TrajectoryEvaluator()
        self.roi_engine = ROIEngine(
            trace_store=self.trace_store,
            audit_store=self.audit_store,
            control_store=self.control_store,
            evaluator=self.trajectory_evaluator,
            default_hourly_infra_rate_usd=self.settings.roi_default_hourly_infra_rate_usd,
            default_fixed_intervention_cost_usd=self.settings.roi_default_fixed_intervention_cost_usd,
            default_tool_execution_cost_usd=self.settings.roi_default_tool_execution_cost_usd,
        )
        self.benchmark_analyzer = HuggingFaceBenchmarkAnalyzer()
        self.phoenix_bridge = ArizePhoenixBridge()

    def reset(self) -> None:
        """Reset internal stores to clean state for test isolation."""
        self._init_stores()
        self.pending_tool_calls.clear()
        self.resolved_overrides.clear()
        self.container_logs.clear()


_container = AppContainer()


def get_container() -> AppContainer:
    """Return the global AppContainer instance."""
    return _container


def get_tenant_context(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    token: Annotated[str | None, Query()] = None,
    baggage: Annotated[str | None, Header(alias="baggage")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_role: Annotated[str | None, Header(alias="X-Role")] = None,
) -> TenantContext:
    """Extract authenticated TenantContext from Bearer token, query token,
    explicit headers, or W3C baggage.
    """
    raw_token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        raw_token = authorization[7:].strip()
    elif token:
        raw_token = token.strip()

    if raw_token:
        try:
            return _container.authenticator.verify_token(raw_token)
        except AuthorizationError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired token: {err}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from err

    settings = _container.settings
    # In non-production tiers (development or testing), allow W3C baggage or dev fallbacks
    if settings.env in (ArgusEnvironment.DEVELOPMENT, ArgusEnvironment.TESTING):
        baggage_map = parse_w3c_baggage(baggage)
        tenant_id = x_tenant_id or baggage_map.get("argus.tenant_id")
        workspace_id = x_workspace_id or baggage_map.get("argus.workspace_id")
        actor_id = x_actor_id or baggage_map.get("argus.actor_id") or "dev_actor"
        raw_role = x_role or baggage_map.get("argus.role")

        role_val = Role.ADMIN
        if raw_role:
            try:
                role_val = Role(raw_role.upper())
            except ValueError:
                role_val = Role.OPERATOR

        if tenant_id and workspace_id:
            return TenantContext(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor_id=actor_id,
                role=role_val,
            )

        if settings.allow_anonymous:
            return TenantContext(
                tenant_id="dev_tenant",
                workspace_id="dev_workspace",
                actor_id="dev_guest",
                role=Role.ADMIN,
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required: Provide a valid Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
