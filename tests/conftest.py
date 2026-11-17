"""Pytest test fixtures and configuration for ResearchOS AI."""

import shutil
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from researchos.api.app import create_app
from researchos.core.config import get_settings
from researchos.memory.db import DatabaseManager
from researchos.memory.migrations.runner import MigrationRunner


@pytest.fixture(scope="session")
def test_temp_dir() -> Path:
    """Provides an isolated temporary directory strictly residing on Drive D:."""
    settings = get_settings()
    base_tmp = Path(settings.paths.temp_dir) / f"pytest_{uuid.uuid4().hex}"
    base_tmp.mkdir(parents=True, exist_ok=True)
    yield base_tmp
    shutil.rmtree(base_tmp, ignore_errors=True)


@pytest.fixture
def isolated_db(test_temp_dir: Path) -> DatabaseManager:
    """Provides a fresh, isolated SQLite database on Drive D: with initial schema migrations applied."""
    db_file = test_temp_dir / f"test_{uuid.uuid4().hex}.db"
    db_manager = DatabaseManager(db_file)
    runner = MigrationRunner(db_manager)
    runner.run_all_migrations()
    return db_manager


@pytest.fixture
def client(isolated_db: DatabaseManager) -> TestClient:
    """Provides a FastAPI TestClient with the isolated test database injected."""
    from researchos.api.routes.health import get_db

    app = create_app(db_manager=isolated_db, run_migrations=False)
    app.dependency_overrides[get_db] = lambda: isolated_db
    with TestClient(app) as test_client:
        yield test_client
