"""ResearchOS AI — System Health & Diagnostics Endpoints."""

import sqlite3
from typing import Annotated, Any

import psutil
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from researchos.core.config import Settings, get_settings
from researchos.memory.db import DatabaseManager

router = APIRouter(tags=["Health & Diagnostics"])


def get_db() -> DatabaseManager:
    """Dependency injecting the configured DatabaseManager."""
    return DatabaseManager()


@router.get("/health", summary="Basic health and readiness check")
def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[DatabaseManager, Depends(get_db)],
) -> JSONResponse:
    """
    Returns system operational health, database connectivity, WAL mode,
    FTS5 availability, and Drive C/D capacity compliance.
    """
    db_healthy = False
    wal_mode = "unknown"
    fts5_ok = False

    try:
        with db.connection() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode;")
            wal_mode = cur.fetchone()[0]
        fts5_ok = db.is_fts5_available()
        db_healthy = wal_mode.lower() == "wal" and fts5_ok
    except (sqlite3.Error, OSError):
        db_healthy = False

    disk_info = settings.verify_disk_thresholds()
    mem = psutil.virtual_memory()

    is_overall_healthy = (
        db_healthy and disk_info["drive_c"]["compliant"] and disk_info["drive_d"]["compliant"]
    )

    payload: dict[str, Any] = {
        "status": "healthy" if is_overall_healthy else "degraded",
        "app_name": settings.app_name,
        "version": settings.app_version,
        "spec_version": settings.spec_version,
        "database": {
            "healthy": db_healthy,
            "journal_mode": wal_mode,
            "fts5_available": fts5_ok,
            "path": str(db.db_path),
        },
        "storage": disk_info,
        "host_resources": {
            "memory_load_percent": mem.percent,
            "available_ram_gib": round(mem.available / (1024**3), 2),
            "total_ram_gib": round(mem.total / (1024**3), 2),
            "cpu_worker_threads_cap": settings.max_worker_threads,
        },
    }

    http_status = status.HTTP_200_OK if is_overall_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=http_status, content=payload)


@router.get("/diagnostics", summary="Detailed environment & storage diagnostics")
def diagnostics(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[DatabaseManager, Depends(get_db)],
) -> dict[str, Any]:
    """Provides detailed diagnostic profiling of storage paths, migrations, and hardware."""
    from researchos.memory.migrations.runner import MigrationRunner

    runner = MigrationRunner(db)
    applied_migrations = runner.get_applied_migrations()

    return {
        "app": {
            "name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
            "spec_version": settings.spec_version,
        },
        "storage_paths": {k: str(v) for k, v in settings.paths.model_dump().items()},
        "isolation_policy": settings.isolation_policy.model_dump(),
        "database": {
            "path": str(db.db_path),
            "applied_migrations": applied_migrations,
        },
        "system": {
            "logical_cores": psutil.cpu_count(logical=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "worker_thread_cap": settings.max_worker_threads,
        },
    }
