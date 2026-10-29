"""Automated tests for the healthy baseline scenario."""

import pytest
from backend.app.engine import (
    SimulatedTelemetryGenerator,
    diagnose,
    get_default_topology,
    run_scenario,
    get_incident_details,
)


def test_baseline_measurements_healthy():
    """Validates that baseline telemetry generates realistic healthy values."""
    generator = SimulatedTelemetryGenerator()
    measurements = generator.generate_measurements(scenario="baseline")

    assert len(measurements) >= 5
    for m in measurements:
        assert m.data_source == "simulated"
        assert m.connectivity_ok is True
        assert m.packet_loss_pct is not None and m.packet_loss_pct <= 1.0
        assert m.latency_ms is not None and m.latency_ms > 0
        assert m.throughput_mbps is not None and m.throughput_mbps > 0


def test_baseline_diagnosis_no_false_faults():
    """Validates that diagnostic algorithm does not identify false faults on healthy network."""
    generator = SimulatedTelemetryGenerator()
    measurements = generator.generate_measurements(scenario="baseline")
    topology = get_default_topology()

    incident = diagnose(measurements=measurements, topology=topology)

    # When all links are healthy, no link should be suspected
    assert incident.suspected_component_id is None
    assert incident.suspected_component_type is None
    assert incident.diagnostic_score is not None and incident.diagnostic_score < 0.10
    assert len(incident.evidence) == 0
    assert "Normal network operation" in incident.summary
    assert incident.uncertainty_note is None


def test_baseline_via_facade():
    """Validates running baseline scenario via HopTrace facade."""
    res = run_scenario(scenario="baseline", force_in_memory=True)
    assert res.data_source == "simulated"
    assert res.measurements_count >= 5
    # For healthy baseline, no open incident is created
    assert res.incident_id is None
