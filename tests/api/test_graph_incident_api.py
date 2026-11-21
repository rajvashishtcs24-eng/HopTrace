"""
Tests for GET /api/v1/incidents/{incident_id}/graph and graph-grounded incident intelligence (Track N2).

Verifies:
1. Unknown incident returns 404.
2. Lab/simulated incident returns backend: "memory", simulated: true, without touching Neo4j.
3. Live incident with unreachable Neo4j falls back gracefully with backend: "memory", fallback: true, no 500.
4. Response schema guarantees:
   - Blast radius count and subscribers list (village, is_essential present).
   - Essential services are prioritized first (is_essential: True before False).
   - Absolutely NO phone numbers in the response.
   - Path contains nodes and links from gateway to failed component.
   - History contains link_id and incidents_30d.
5. Failed nodes as well as failed links are supported in path and blast radius.
6. History fallback reads from SQLite incidents table.
7. Outage notification recipients are reconciled against SQLite subscribers table,
   logging mismatches and sending only to SQLite-reconciled subscribers.
"""
from __future__ import annotations

import logging
from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.connection import get_db_connection
from app.db.repository import create_incident
from app.main import app
from app.schemas.graph import IncidentGraphResponse


@pytest.fixture
def test_client(isolated_db: str) -> TestClient:
    """Provides a TestClient connected to the isolated SQLite database."""
    return TestClient(app)


def test_get_incident_graph_404_not_found(test_client: TestClient) -> None:
    """Querying an unknown incident returns HTTP 404."""
    resp = test_client.get("/api/v1/incidents/nonexistent-incident-999/graph")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_get_incident_graph_simulated_incident(test_client: TestClient, isolated_db: str) -> None:
    """Simulated/lab incidents return backend: 'memory' and simulated: true without hitting Neo4j."""
    # incident-demo-001 is seeded by default in isolated_db with data_source: simulated
    resp = test_client.get("/api/v1/incidents/incident-demo-001/graph")
    assert resp.status_code == 200
    data = resp.json()

    # Validate schema via Pydantic
    parsed = IncidentGraphResponse(**data)
    assert parsed.backend == "memory"
    assert parsed.simulated is True
    assert parsed.fallback is False

    # Blast radius checks (L3 connects WB1->WB2 in Village 1 Rampur, feeds AP1)
    assert parsed.blast_radius.count > 0
    sub_ids = [s.id for s in parsed.blast_radius.subscribers]
    assert "SUB101" in sub_ids
    assert "SUB102" in sub_ids

    # Path check: GW1 -> R1 -> WB1 -> WB2
    assert "GW1" in parsed.path.nodes
    assert "L1" in parsed.path.links

    # History from SQLite
    assert parsed.history.link_id == "L3"
    assert isinstance(parsed.history.incidents_30d, int)


def test_get_incident_graph_no_phone_numbers_leaked(test_client: TestClient) -> None:
    """Requirement: Absolutely NO phone numbers in the graph endpoint."""
    resp = test_client.get("/api/v1/incidents/incident-demo-001/graph")
    assert resp.status_code == 200
    raw_text = resp.text
    data = resp.json()

    # Neither the key nor any +91 phone numbers appear
    assert "phone" not in raw_text
    assert "+91" not in raw_text

    for sub in data["blast_radius"]["subscribers"]:
        assert "phone" not in sub
        assert "phone_number" not in sub
        assert "id" in sub
        assert "name" in sub
        assert "village" in sub
        assert "is_essential" in sub


def test_get_incident_graph_essential_services_sorted_first(
    test_client: TestClient,
    isolated_db: str,
) -> None:
    """Essential services (PHC, Hospital, Sarpanch, School, etc.) sort to the top of blast radius."""
    conn = get_db_connection(isolated_db)
    try:
        # Create an incident on L14 (WB6 -> AP6, which serves Daulatpur Hospital and ITI College)
        create_incident(
            conn,
            {
                "id": "inc-essential-test",
                "status": "open",
                "suspected_component_id": "L14",
                "suspected_component_type": "link",
                "summary": "Downstream AP6 link failure",
                "data_source": "simulated",
            },
        )
    finally:
        conn.close()

    resp = test_client.get("/api/v1/incidents/inc-essential-test/graph")
    assert resp.status_code == 200
    subs = resp.json()["blast_radius"]["subscribers"]
    assert len(subs) > 0

    # Ensure all is_essential==True items come before is_essential==False items
    seen_non_essential = False
    for sub in subs:
        if sub["is_essential"]:
            assert not seen_non_essential, "Found essential service after non-essential in sorted list!"
        else:
            seen_non_essential = True


def test_get_incident_graph_handles_failed_node(
    test_client: TestClient,
    isolated_db: str,
) -> None:
    """Requirement: Handle failed nodes (e.g. WB3, R2, AP1) as well as links in path and blast radius."""
    conn = get_db_connection(isolated_db)
    try:
        create_incident(
            conn,
            {
                "id": "inc-node-wb3-test",
                "status": "open",
                "suspected_component_id": "WB3",
                "suspected_component_type": "node",
                "summary": "Wireless Bridge WB3 power loss",
                "data_source": "simulated",
            },
        )
    finally:
        conn.close()

    resp = test_client.get("/api/v1/incidents/inc-node-wb3-test/graph")
    assert resp.status_code == 200
    data = resp.json()

    # Path to WB3: GW1 -> R1 -> WB3 (links: L1, L6)
    assert data["path"]["nodes"] == ["GW1", "R1", "WB3"]
    assert data["path"]["links"] == ["L1", "L6"]

    # WB3 is uplink for Village 2 (Bhatpur, AP3 & AP4)
    sub_ids = [s["id"] for s in data["blast_radius"]["subscribers"]]
    assert "SUB301" in sub_ids
    assert "SUB401" in sub_ids


def test_get_incident_graph_live_source_fallback_when_neo4j_down(
    test_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    isolated_db: str,
) -> None:
    """When a live incident is queried with Neo4j down, it falls back to memory with fallback: true."""
    from app.engine.facade import get_engine

    conn = get_db_connection(isolated_db)
    try:
        create_incident(
            conn,
            {
                "id": "inc-live-offline-test",
                "status": "open",
                "suspected_component_id": "L6",
                "suspected_component_type": "link",
                "summary": "Live fault on L6",
                "data_source": "live",
            },
        )
    finally:
        conn.close()

    engine = get_engine()
    engine._neo4j_fallback = False
    engine._probe_failed_at = None

    monkeypatch.setattr(settings, "graph_backend", "auto")
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://127.0.0.1:1")
    monkeypatch.setattr(settings, "neo4j_user", "neo4j")
    monkeypatch.setattr(settings, "neo4j_password", "fake_pass")

    resp = test_client.get("/api/v1/incidents/inc-live-offline-test/graph")
    assert resp.status_code == 200
    data = resp.json()

    assert data["backend"] == "memory"
    assert data["fallback"] is True
    assert data["simulated"] is False

    # Path to L6 target (WB3)
    assert data["path"]["nodes"] == ["GW1", "R1", "WB3"]
    assert data["path"]["links"] == ["L1", "L6"]
    assert data["history"]["link_id"] == "L6"


def test_notify_reconciliation_logs_warning_and_filters_unreconciled(
    test_client: TestClient,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    isolated_db: str,
) -> None:
    """Requirement: Notify recipients are reconciled against SQLite subscribers table:

    log mismatches and send only to the SQLite-reconciled list.
    """
    from app.providers.registry import get_dependency_adapter

    monkeypatch.setattr(settings, "explanation_provider", "simulated")

    class MockAdapter:
        def get_affected_subscribers(self, *args, **kwargs):
            return [
                {"id": "SUB101", "display_name": "Rampur CSC", "access_point_id": "AP1"},
                {"id": "SUB_GHOST_999", "display_name": "Ghost User", "access_point_id": "AP99"},
            ]

    app.dependency_overrides[get_dependency_adapter] = MockAdapter

    try:
        with caplog.at_level(logging.WARNING):
            resp = test_client.get("/api/v1/incidents/incident-demo-001/notifications/preview")
    finally:
        app.dependency_overrides.pop(get_dependency_adapter, None)

    assert resp.status_code == 200
    previews = resp.json()["previews"]

    # Only SUB101 is reconciled and retained in the notification preview list
    recip_ids = [p["subscriber_id"] for p in previews]
    assert "SUB101" in recip_ids
    assert "SUB_GHOST_999" not in recip_ids

    # Warning was logged for the mismatched subscriber
    assert any("SUB_GHOST_999" in record.message for record in caplog.records)
