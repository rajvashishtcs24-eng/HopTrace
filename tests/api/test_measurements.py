"""
Automated tests for Run Measurements endpoint (Milestone 5).

Tests:
1. GET /api/v1/runs/{run_id}/measurements succeeds for a valid run.
2. GET /api/v1/runs/{run_id}/measurements returns 404 for unknown run_id.
3. Response structure strictly adheres to docs/api-contract.md Section 7.
4. Measurements for degraded scenario contain expected telemetry observations.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_get_measurements_valid_run(client: TestClient) -> None:
    """A generated test run returns 200 with complete telemetry observations."""
    # 1. Generate a test run via lab endpoint
    lab_resp = client.post(
        "/api/v1/lab/run",
        json={"scenario": "baseline"},
    )
    assert lab_resp.status_code == 200
    run_id = lab_resp.json()["run_id"]
    assert run_id

    # 2. Retrieve measurements for that run
    meas_resp = client.get(f"/api/v1/runs/{run_id}/measurements")
    assert meas_resp.status_code == 200

    data = meas_resp.json()
    assert data["run_id"] == run_id
    assert data["data_source"] in ("simulated", "measured")
    assert isinstance(data["measurements"], list)
    assert len(data["measurements"]) > 0

    # 3. Verify each measurement conforms to schema
    for m in data["measurements"]:
        assert "component_id" in m
        assert "timestamp_utc" in m
        assert "connectivity_ok" in m
        assert "data_source" in m
        assert m["data_source"] in ("simulated", "measured")
        assert isinstance(m["connectivity_ok"], bool)
        # Nullable numeric fields
        assert m.get("latency_ms") is None or isinstance(m["latency_ms"], (int, float))
        assert m.get("packet_loss_pct") is None or isinstance(m["packet_loss_pct"], (int, float))
        assert m.get("throughput_mbps") is None or isinstance(m["throughput_mbps"], (int, float))


def test_get_measurements_not_found(client: TestClient) -> None:
    """Non-existent run_id returns HTTP 404 with a meaningful detail message."""
    resp = client.get("/api/v1/runs/non-existent-run-9999/measurements")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_get_measurements_degraded_scenario(client: TestClient) -> None:
    """Degraded link test run preserves measurements and reports expected data source."""
    lab_resp = client.post(
        "/api/v1/lab/run",
        json={
            "scenario": "degrade_link",
            "target_link_id": "L3",
            "severity": "high",
        },
    )
    assert lab_resp.status_code == 200
    run_id = lab_resp.json()["run_id"]

    meas_resp = client.get(f"/api/v1/runs/{run_id}/measurements")
    assert meas_resp.status_code == 200
    data = meas_resp.json()
    assert data["run_id"] == run_id
    assert data["data_source"] == "simulated"
    # Find degraded link measurement
    l3_meas = next((m for m in data["measurements"] if m["component_id"] == "L3"), None)
    assert l3_meas is not None
    assert l3_meas["latency_ms"] is not None
    assert l3_meas["latency_ms"] > 25.0  # High degradation increases latency
