"""ResearchOS AI — FastAPI Backend Application Factory & Lifespan Context."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from researchos.api.routes.health import router as health_router
from researchos.core.config import get_settings
from researchos.core.exceptions import (
    ApprovalRequiredError,
    PathContainmentError,
    ResearchOSError,
    SecurityError,
    StorageIsolationError,
)
from researchos.core.logging import get_logger, setup_logging
from researchos.memory.db import DatabaseManager
from researchos.memory.migrations.runner import MigrationRunner

logger = get_logger("api.app")


def create_app(
    db_manager: DatabaseManager | None = None,
    run_migrations: bool = True,
) -> FastAPI:
    """Creates and configures the FastAPI application instance."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Manages application lifecycle: directory creation, DB initialization, and migrations."""
        setup_logging()
        logger.info(
            f"Starting {settings.app_name} v{settings.app_version} (Spec v{settings.spec_version})"
        )

        if run_migrations:
            # 1. Enforce directory creation on Drive D:
            settings.ensure_directories()

            # 2. Initialize database and apply migrations
            db = db_manager or DatabaseManager()
            runner = MigrationRunner(db)
            applied = runner.run_all_migrations()
            logger.info(f"Database initialized at {db.db_path}. Applied migrations: {applied}")

        yield

        logger.info(f"Shutting down {settings.app_name} daemon.")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Unified Personal AI Operating System — Backend IPC Daemon",
        lifespan=lifespan,
    )

    # Configure CORS for local development and IPC
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost", "http://127.0.0.1:8000"],
        allow_origin_regex=r"^http://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Domain Exception Handlers
    @app.exception_handler(ApprovalRequiredError)
    async def approval_required_handler(
        request: Request, exc: ApprovalRequiredError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": "ApprovalRequiredError",
                "message": exc.message,
                "requires_approval": True,
            },
        )

    @app.exception_handler(PathContainmentError)
    @app.exception_handler(StorageIsolationError)
    async def path_error_handler(request: Request, exc: ResearchOSError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": type(exc).__name__, "message": exc.message},
        )

    @app.exception_handler(SecurityError)
    async def security_error_handler(request: Request, exc: SecurityError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "SecurityViolation", "message": exc.message},
        )

    @app.exception_handler(ResearchOSError)
    async def general_domain_error_handler(request: Request, exc: ResearchOSError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": type(exc).__name__, "message": exc.message},
        )

    # Register Routers
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(health_router)  # Also expose /health at root for simple probes

    return app


# Default module-level app instance for ASGI servers (Uvicorn)
app = create_app()
