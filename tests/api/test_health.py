"""
Tests for GET /api/v1/health.

Verifies:
  - HTTP 200 status code.
  - Exact JSON response body: {"status": "ok", "version": "0.1.0"}.
"""
from fastapi.testclient import TestClient


def test_health_status_code(client: TestClient) -> None:
    """Health endpoint must return HTTP 200."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_health_exact_json(client: TestClient) -> None:
    """Health endpoint must return the exact payload specified in the API contract."""
    response = client.get("/api/v1/health")
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_health_content_type(client: TestClient) -> None:
    """Health endpoint must return JSON."""
    response = client.get("/api/v1/health")
    assert response.headers["content-type"].startswith("application/json")
