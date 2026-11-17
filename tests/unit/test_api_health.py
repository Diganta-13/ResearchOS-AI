"""Unit tests for FastAPI health and diagnostic endpoints."""

from starlette.testclient import TestClient


def test_health_endpoint_root(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
    assert data["database"]["healthy"] is True
    assert data["database"]["journal_mode"].lower() == "wal"
    assert data["database"]["fts5_available"] is True
    assert data["storage"]["drive_c"]["compliant"] is True
    assert data["storage"]["drive_d"]["compliant"] is True


def test_health_endpoint_v1(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_diagnostics_endpoint(client: TestClient):
    response = client.get("/api/v1/diagnostics")
    assert response.status_code == 200
    data = response.json()
    assert "app" in data
    assert "storage_paths" in data
    assert "database" in data
    # JSON dictionary keys are strings
    assert "1" in data["database"]["applied_migrations"]
