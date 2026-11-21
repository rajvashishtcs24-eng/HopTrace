"""
Tests for Track N1:
- GRAPH_BACKEND setting ('auto', 'memory', 'neo4j')
- Negative-caching probe with 30s backoff
- Topology cache locking and invalidation on seed
- Mid-run Neo4j failure with graceful in-memory fallback (no 500)
- Error sanitization (no URI, username, or password in last_error)
- GET /api/v1/graph/status endpoint schema and behavior
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.engine.facade import HopTraceEngine, get_engine, get_graph_status
from app.engine.graph_store import InMemoryGraphStore, Neo4jGraphStore
from app.engine.neo4j_client import sanitize_last_error
from app.main import app


def _reset_engine():
    """Resets the singleton engine instance for test isolation."""
    import app.engine.facade as facade_module
    facade_module._engine_instance = None


def test_graph_backend_memory_always_in_memory(monkeypatch):
    """When GRAPH_BACKEND=memory, get_active_store always returns InMemoryGraphStore."""
    monkeypatch.setattr(settings, "graph_backend", "memory")
    _reset_engine()

    engine = get_engine()
    # verify check_connection is never called
    engine.neo4j_client.check_connection = MagicMock(side_effect=RuntimeError("Must not call Neo4j"))
    store = engine.get_active_store()

    assert isinstance(store, InMemoryGraphStore)
    assert engine.is_neo4j_available() is False
    engine.neo4j_client.check_connection.assert_not_called()
    _reset_engine()


def test_negative_cache_availability_probe(monkeypatch):
    """When Neo4j probe fails, subsequent checks within 30s backoff window do not re-probe."""
    monkeypatch.setattr(settings, "graph_backend", "auto")
    _reset_engine()

    engine = get_engine()
    engine.neo4j_client.uri = "bolt://localhost:7687"
    engine.neo4j_client.check_connection = MagicMock(return_value={
        "connected": False,
        "error": "Connection refused to bolt://localhost:7687",
    })

    # First check: probes and fails
    assert engine.is_neo4j_available() is False
    assert engine.neo4j_client.check_connection.call_count == 1
    assert engine._neo4j_fallback is True

    # Second check immediately after: negative-cached, must NOT probe again
    assert engine.is_neo4j_available() is False
    assert engine.neo4j_client.check_connection.call_count == 1  # Still 1!

    _reset_engine()


def test_topology_cache_locked_and_invalidated_on_seed(monkeypatch):
    """Topology cache avoids repeated Neo4j queries and invalidates on seed_topology."""
    monkeypatch.setattr(settings, "graph_backend", "auto")
    monkeypatch.setattr(settings, "graph_topology_cache_ttl", 120)
    _reset_engine()

    engine = get_engine()
    engine.neo4j_client.uri = "bolt://localhost:7687"
    # Mock Neo4j as connected
    engine.neo4j_client.check_connection = MagicMock(return_value={"connected": True})

    # Seed in-memory mirror and mock Neo4j store
    mock_topo = engine.in_memory_store.get_topology()
    engine.neo4j_store.get_topology = MagicMock(return_value=mock_topo)
    engine.neo4j_store.seed_topology = MagicMock(return_value={"status": "seeded"})

    # First get_topology: loads from Neo4j
    topo1 = engine.get_topology()
    assert topo1 is not None
    assert engine.neo4j_store.get_topology.call_count == 1

    # Second get_topology within TTL: returns cached snapshot without hitting Neo4j
    topo2 = engine.get_topology()
    assert topo2 is not None
    assert engine.neo4j_store.get_topology.call_count == 1  # Still 1!

    # seed_topology() must invalidate cache under lock
    engine.seed_topology()
    assert engine._topology_cache is None

    # Third get_topology: cache is invalidated, hits store again
    topo3 = engine.get_topology()
    assert topo3 is not None
    assert engine.neo4j_store.get_topology.call_count == 2

    _reset_engine()


def test_mid_run_neo4j_failure_falls_back_without_500(monkeypatch):
    """When Neo4j fails mid-run, operations fallback to in-memory store and no 500 is raised."""
    monkeypatch.setattr(settings, "graph_backend", "auto")
    _reset_engine()

    engine = get_engine()
    engine.neo4j_client.uri = "bolt://localhost:7687"
    engine.seed_topology(force_in_memory=True)

    # Initially mock Neo4j as healthy
    engine.neo4j_client.check_connection = MagicMock(return_value={"connected": True})
    assert engine.is_neo4j_available() is True

    # Neo4j fails mid-run with an unexpected driver error
    engine.neo4j_store.get_topology = MagicMock(side_effect=Exception("Driver socket reset by peer"))

    # Calling get_topology must not raise an unhandled 500, but fall back to memory
    topo = engine.get_topology()
    assert topo is not None
    assert len(topo.nodes) > 0
    assert engine._neo4j_fallback is True
    assert "Driver socket reset by peer" in (engine._neo4j_last_error or "")

    # Status endpoint reflects fallback
    client = TestClient(app)
    resp = client.get("/api/v1/graph/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["backend"] == "memory"
    assert data["fallback"] is True

    _reset_engine()


def test_sanitize_last_error_removes_uri_user_password():
    """sanitize_last_error ensures no URI, username, or password appears in error messages."""
    raw_error = (
        "Failed to establish connection to neo4j+s://admin_user:super_secret_p@wd123@db77.databases.neo4j.io:7687: "
        "authentication failed for user 'admin_user'."
    )
    cleaned = sanitize_last_error(
        raw_error,
        password="super_secret_p@wd123",
        username="admin_user",
        uri="neo4j+s://admin_user:super_secret_p@wd123@db77.databases.neo4j.io:7687",
    )

    assert "super_secret_p@wd123" not in cleaned
    assert "admin_user" not in cleaned
    assert "db77.databases.neo4j.io" not in cleaned
    assert "neo4j+s://" not in cleaned
    assert "[REDACTED_URI]" in cleaned or "***" in cleaned


def test_get_graph_status_endpoint_offline(monkeypatch):
    """GET /api/v1/graph/status returns structured status when Neo4j is offline with configured URI."""
    monkeypatch.setattr(settings, "graph_backend", "auto")
    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:9999")
    _reset_engine()

    engine = get_engine()
    engine.neo4j_client.uri = "bolt://127.0.0.1:9999"
    engine.neo4j_client.check_connection = MagicMock(return_value={
        "connected": False,
        "error": "Connection refused at bolt://127.0.0.1:9999",
    })

    client = TestClient(app)
    resp = client.get("/api/v1/graph/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["backend"] == "memory"
    assert data["fallback"] is True
    assert data["last_error"] is not None
    assert "bolt://" not in data["last_error"]  # Sanitized!

    _reset_engine()


def test_get_graph_status_endpoint_unconfigured(monkeypatch):
    """When credentials are not configured, GET /api/v1/graph/status returns fallback: false and reason: 'not_configured'."""
    monkeypatch.setattr(settings, "graph_backend", "auto")
    monkeypatch.delenv("NEO4J_URI", raising=False)
    _reset_engine()

    engine = get_engine()
    engine.neo4j_client.uri = None

    client = TestClient(app)
    resp = client.get("/api/v1/graph/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["backend"] == "memory"
    assert data["fallback"] is False
    assert data["reason"] == "not_configured"
    assert data["last_error"] is None

    _reset_engine()


def test_get_graph_status_endpoint_memory_mode(monkeypatch):
    """GET /api/v1/graph/status with GRAPH_BACKEND=memory returns backend=memory and fallback=False."""
    monkeypatch.setattr(settings, "graph_backend", "memory")
    _reset_engine()

    client = TestClient(app)
    resp = client.get("/api/v1/graph/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["backend"] == "memory"
    assert data["fallback"] is False
    assert data["latency_ms"] is None
    assert data["last_error"] is None

    _reset_engine()
