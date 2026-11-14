"""Argus Control Plane FastAPI Application entry point."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.staticfiles import StaticFiles

from argus.api.dependencies import get_container
from argus.api.routes.attribution import router as attribution_router
from argus.api.routes.c2 import router as c2_router
from argus.api.routes.demo import router as demo_router
from argus.api.routes.governance import router as governance_router
from argus.api.routes.stream import router as stream_router
from argus.api.routes.telemetry import router as telemetry_router
from argus.core.errors import (
    ArgusError,
    AuthorizationError,
    BudgetExceededError,
    CheckpointConflictError,
    EntityNotFoundError,
    InvalidStateTransitionError,
    TenantIsolationError,
)
from argus.core.schemas import SessionStatus
from argus.core.tenancy import Role, TenantContext


def create_app() -> FastAPI:
    """Instantiate and configure the Argus Control Plane FastAPI application."""
    app = FastAPI(
        title="Argus AgentOps & C2 Control Plane",
        description=(
            "Zero-tolerance governance, observability, and Command & Control plane "
            "for autonomous AI agents."
        ),
        version="0.1.0",
    )

    # Permit frontend dashboard cross-origin requests
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global domain exception handlers
    @app.exception_handler(EntityNotFoundError)
    async def entity_not_found_handler(request: Request, exc: EntityNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "EntityNotFound", "detail": str(exc)},
        )

    @app.exception_handler(CheckpointConflictError)
    async def checkpoint_conflict_handler(
        request: Request, exc: CheckpointConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "CheckpointConflict", "detail": str(exc)},
        )

    @app.exception_handler(InvalidStateTransitionError)
    async def invalid_transition_handler(
        request: Request, exc: InvalidStateTransitionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "InvalidStateTransition", "detail": str(exc)},
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(
        request: Request, exc: AuthorizationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "AuthorizationError", "detail": str(exc)},
        )

    @app.exception_handler(TenantIsolationError)
    async def tenant_isolation_handler(
        request: Request, exc: TenantIsolationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "TenantIsolationError", "detail": str(exc)},
        )

    @app.exception_handler(BudgetExceededError)
    async def budget_exceeded_handler(
        request: Request, exc: BudgetExceededError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={"error": "BudgetExceeded", "detail": str(exc)},
        )

    @app.exception_handler(ArgusError)
    async def generic_argus_handler(request: Request, exc: ArgusError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "ArgusError", "detail": str(exc)},
        )

    # Mount API routers
    app.include_router(telemetry_router)
    app.include_router(governance_router)
    app.include_router(c2_router)
    app.include_router(attribution_router)
    app.include_router(demo_router)
    app.include_router(stream_router)

    # Mount compiled dashboard UI if available
    dashboard_dist = Path(__file__).resolve().parents[3] / "dashboard" / "dist"
    if dashboard_dist.exists():
        app.mount(
            "/dashboard",
            StaticFiles(directory=str(dashboard_dist), html=True),
            name="dashboard",
        )

    @app.get("/healthz", tags=["System"])
    async def health_check() -> dict[str, str]:
        """Liveness probe endpoint for container orchestrators."""
        return {"status": "HEALTHY", "service": "argus-control-plane", "version": "0.1.0"}

    @app.get("/readyz", tags=["System"])
    async def readiness_check() -> dict[str, str]:
        """Readiness probe verifying internal control and telemetry stores."""
        container = get_container()
        is_ready = (
            container.trace_store is not None
            and container.control_store is not None
            and container.budget_store is not None
            and container.audit_store is not None
        )
        return {
            "status": "READY" if is_ready else "DEGRADED",
            "service": "argus-control-plane",
        }

    @app.get("/metrics", response_class=PlainTextResponse, tags=["System"])
    async def prometheus_metrics() -> str:
        """Export operational telemetry in Prometheus text exposition format."""
        container = get_container()
        default_ctx = TenantContext(
            tenant_id="default_tenant",
            workspace_id="default_workspace",
            actor_id="metrics_scraper",
            role=Role.VIEWER,
        )
        sessions = await container.control_store.list_sessions(default_ctx)
        running_count = sum(1 for s in sessions if s.status == SessionStatus.RUNNING)
        paused_count = sum(1 for s in sessions if s.status == SessionStatus.PAUSED_C2)
        tripped_count = sum(
            1
            for s in sessions
            if s.status in (SessionStatus.TRIPPED_LOOP, SessionStatus.TRIPPED_BUDGET)
        )
        total_spend = sum(s.accumulated_cost_usd for s in sessions)
        pending_tools = sum(len(calls) for calls in container.pending_tool_calls.values())

        lines = [
            "# HELP argus_sessions_total Total tracked autonomous agent sessions.",
            "# TYPE argus_sessions_total gauge",
            f"argus_sessions_total {len(sessions)}",
            "# HELP argus_sessions_running Currently running agent sessions.",
            "# TYPE argus_sessions_running gauge",
            f"argus_sessions_running {running_count}",
            "# HELP argus_sessions_paused_c2 Agent sessions paused awaiting human C2 intervention.",
            "# TYPE argus_sessions_paused_c2 gauge",
            f"argus_sessions_paused_c2 {paused_count}",
            "# HELP argus_circuit_breakers_tripped Sessions halted by circuit breakers.",
            "# TYPE argus_circuit_breakers_tripped gauge",
            f"argus_circuit_breakers_tripped {tripped_count}",
            "# HELP argus_pending_tool_interventions_total Pending MCP calls awaiting override.",
            "# TYPE argus_pending_tool_interventions_total gauge",
            f"argus_pending_tool_interventions_total {pending_tools}",
            "# HELP argus_accumulated_spend_usd Total accumulated token and tool spend in USD.",
            "# TYPE argus_accumulated_spend_usd gauge",
            f"argus_accumulated_spend_usd {total_spend:.6f}",
        ]
        return "\n".join(lines) + "\n"

    @app.get("/", tags=["System"])
    async def root_index() -> dict[str, str]:
        """Root API summary."""
        return {
            "name": "Argus C2 Control Plane API",
            "docs_url": "/docs",
            "openapi_url": "/openapi.json",
            "dashboard_url": "/dashboard",
        }

    return app


app = create_app()
