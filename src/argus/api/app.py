"""Argus Control Plane FastAPI Application entry point."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from argus.api.routes.attribution import router as attribution_router
from argus.api.routes.c2 import router as c2_router
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
        """Health check endpoint for container orchestrators and readiness probes."""
        return {"status": "HEALTHY", "service": "argus-control-plane", "version": "0.1.0"}

    @app.get("/", tags=["System"])
    async def root_index() -> dict[str, str]:
        """Root API summary."""
        return {
            "name": "Argus C2 Control Plane API",
            "docs_url": "/docs",
            "openapi_url": "/openapi.json",
        }

    return app


app = create_app()
