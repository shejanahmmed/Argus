"""Dependency injection providers and container for the Argus Control Plane API."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from argus.adapters_infra.in_memory import (
    InMemoryAuditStore,
    InMemoryBudgetStore,
    InMemoryControlStore,
    InMemoryEventBus,
    InMemoryTraceStore,
)
from argus.attribution.hf_benchmarks import HuggingFaceBenchmarkAnalyzer
from argus.attribution.roi_engine import ROIEngine
from argus.c2.audit_ledger import C2AuditLedger
from argus.c2.state_manager import C2StateManager
from argus.c2.tool_override import ToolOverrideEngine
from argus.core.schemas import PendingToolCall
from argus.core.tenancy import Role, TenantContext
from argus.governance.budget_guard import BudgetGuard
from argus.governance.loop_detector import LoopDetector
from argus.ports.repositories import (
    AuditStore,
    BudgetStore,
    ControlStore,
    EventBus,
    TraceStore,
)


class AppContainer:
    """Singleton container managing operational state, stores, and engines."""

    def __init__(self) -> None:
        self.trace_store: TraceStore = InMemoryTraceStore()
        self.control_store: ControlStore = InMemoryControlStore()
        self.budget_store: BudgetStore = InMemoryBudgetStore()
        self.audit_store: AuditStore = InMemoryAuditStore()
        self.event_bus: EventBus = InMemoryEventBus()

        self.audit_ledger = C2AuditLedger(audit_store=self.audit_store)
        self.loop_detector = LoopDetector()
        self.budget_guard = BudgetGuard(backend=self.budget_store)
        self.c2_state_manager = C2StateManager(control_store=self.control_store)
        self.tool_override_engine = ToolOverrideEngine()
        self.roi_engine = ROIEngine(trace_store=self.trace_store)
        self.benchmark_analyzer = HuggingFaceBenchmarkAnalyzer()

        # In-memory tracking for pending intercepted tool calls: session_id -> list[PendingToolCall]
        self.pending_tool_calls: dict[str, list[PendingToolCall]] = {}

    def reset(self) -> None:
        """Reset internal stores to clean state for test isolation."""
        self.trace_store = InMemoryTraceStore()
        self.control_store = InMemoryControlStore()
        self.budget_store = InMemoryBudgetStore()
        self.audit_store = InMemoryAuditStore()
        self.event_bus = InMemoryEventBus()

        self.audit_ledger = C2AuditLedger(audit_store=self.audit_store)
        self.loop_detector = LoopDetector()
        self.budget_guard = BudgetGuard(backend=self.budget_store)
        self.c2_state_manager = C2StateManager(control_store=self.control_store)
        self.tool_override_engine = ToolOverrideEngine()
        self.roi_engine = ROIEngine(trace_store=self.trace_store)
        self.pending_tool_calls.clear()


_container = AppContainer()


def get_container() -> AppContainer:
    """Return the global AppContainer instance."""
    return _container


def get_tenant_context(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_role: Annotated[str | None, Header(alias="X-Role")] = None,
) -> TenantContext:
    """Extract authenticated TenantContext from incoming request headers."""
    tenant_id = x_tenant_id or "default_tenant"
    workspace_id = x_workspace_id or "default_workspace"
    actor_id = x_actor_id or "operator_admin"

    role_val = Role.ADMIN
    if x_role:
        try:
            role_val = Role(x_role.upper())
        except ValueError:
            role_val = Role.OPERATOR

    return TenantContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        role=role_val,
    )
