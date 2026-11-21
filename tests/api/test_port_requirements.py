"""
Tests for Neo4j port and Track M3 safety requirements:
1. Non-live incidents route to console sandbox even when Twilio is configured.
2. NOTIFY_MAX_RECIPIENTS capping works as expected.
3. Graph endpoints (/api/v1/graph/status and /api/v1/incidents/{incident_id}/graph) enforce RBAC.
4. sandboxed_count is returned in NotificationSendResponse.
"""
from __future__ import annotations

import sqlite3
import pytest
from fastapi.testclient import TestClient

from app.auth.security import create_access_token
from app.config import settings
from app.db.init import init_db


@pytest.fixture
def test_db(tmp_path) -> str:
    db_file = str(tmp_path / "test_port.db")
    init_db(db_file, seed_demo=True)
    return db_file


def test_non_live_incident_routes_to_console_sandbox_when_twilio_configured(
    client: TestClient, isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When Twilio is configured, non-live (simulated/lab) incidents are safely routed to console sandbox."""
    monkeypatch.setattr(settings, "notification_provider", "twilio")
    monkeypatch.setattr(settings, "twilio_account_sid", "AC" + "x" * 32)
    monkeypatch.setattr(settings, "twilio_auth_token", "test_auth_token_32chars")
    monkeypatch.setattr(settings, "twilio_from_number", "+15551234567")
    monkeypatch.setattr(settings, "real_send_allowlist", "+919800000101,+919800000201")

    # incident-demo-001 has data_source = 'simulated'
    resp = client.post(
        "/api/v1/incidents/incident-demo-001/notify",
        headers={"Idempotency-Key": "test-key-sim-sandbox"},
        json={"channel": "sms", "kind": "outage"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "console"
    assert data["sandboxed_count"] > 0
    assert data["sent_count"] > 0
    assert all(d["sandboxed"] is True for d in data["deliveries"])
    assert all(d["provider"] == "console" for d in data["deliveries"])


def test_notify_max_recipients_cap(
    client: TestClient, isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NOTIFY_MAX_RECIPIENTS caps the recipient list when exceeded."""
    monkeypatch.setattr(settings, "notification_provider", "console")
    monkeypatch.setattr(settings, "notify_max_recipients", 1)

    resp = client.post(
        "/api/v1/incidents/incident-demo-001/notify",
        headers={"Idempotency-Key": "test-key-cap-1"},
        json={"channel": "sms", "kind": "outage"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_targeted"] == 1
    assert len(data["deliveries"]) == 1
    assert data["sent_count"] == 1
    assert data["sandboxed_count"] == 1


def test_graph_endpoints_enforce_rbac(
    client: TestClient, isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Graph status and incident graph endpoints require authentication and allow viewer/operator."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "auth_secret", "super-secret-test-auth-key-32chars-min!")

    # 1. Unauthenticated request to /api/v1/graph/status returns 401
    resp_anon = client.get("/api/v1/graph/status")
    assert resp_anon.status_code == 401

    # 2. Unauthenticated request to /api/v1/incidents/{id}/graph returns 401
    resp_anon_inc = client.get("/api/v1/incidents/incident-demo-001/graph")
    assert resp_anon_inc.status_code == 401

    # 3. Viewer token can access both
    viewer_token, _ = create_access_token("alice", "viewer", settings.auth_secret)
    v_headers = {"Authorization": f"Bearer {viewer_token}"}
    resp_viewer_status = client.get("/api/v1/graph/status", headers=v_headers)
    assert resp_viewer_status.status_code == 200

    resp_viewer_inc = client.get("/api/v1/incidents/incident-demo-001/graph", headers=v_headers)
    assert resp_viewer_inc.status_code == 200

    # 4. Operator token can access both
    op_token, _ = create_access_token("bob", "operator", settings.auth_secret)
    op_headers = {"Authorization": f"Bearer {op_token}"}
    resp_op_status = client.get("/api/v1/graph/status", headers=op_headers)
    assert resp_op_status.status_code == 200
