"""Automated tests for handling missing measurements without treating them as healthy."""

import pytest
from backend.app.engine import (
    DiagnosticEngine,
    Measurement,
    SimulatedTelemetryGenerator,
    diagnose,
    get_default_topology,
)


def test_missing_measurements_not_treated_as_healthy():
    """Validates that a link with null/missing telemetry is NOT assumed healthy."""
    generator = SimulatedTelemetryGenerator()
    # Link L3 telemetry is omitted/null
    measurements = generator.generate_measurements(
        scenario="missing_measurements",
        missing_link_ids=["L3"],
    )
    topology = get_default_topology()

    incident = diagnose(measurements=measurements, topology=topology)

    # Uncertainty note must be present
    assert incident.uncertainty_note is not None
    assert "L3" in incident.uncertainty_note
    assert "missing" in incident.uncertainty_note.lower()

    # The confidence score must NOT claim 100% verified health
    assert incident.confidence_score is None or incident.confidence_score < 1.0


def test_completely_omitted_link_detected_as_unmonitored():
    """Validates that completely omitting a link from observations flags unmonitored status."""
    engine = DiagnosticEngine()
    # Provide measurements for all links EXCEPT L4
    measurements = [
        Measurement(
            component_id="L1",
            latency_ms=15.0,
            packet_loss_pct=0.0,
            throughput_mbps=100.0,
            connectivity_ok=True,
        ),
        Measurement(
            component_id="L2",
            latency_ms=2.0,
            packet_loss_pct=0.0,
            throughput_mbps=80.0,
            connectivity_ok=True,
        ),
        Measurement(
            component_id="L3",
            latency_ms=25.0,
            packet_loss_pct=0.5,
            throughput_mbps=35.0,
            connectivity_ok=True,
        ),
        # L4 is missing!
        Measurement(
            component_id="L5",
            latency_ms=5.0,
            packet_loss_pct=0.0,
            throughput_mbps=60.0,
            connectivity_ok=True,
        ),
    ]
    topology = get_default_topology()

    incident = engine.diagnose(measurements=measurements, topology=topology)

    assert incident.uncertainty_note is not None
    assert "L4" in incident.uncertainty_note
    # Must state that health cannot be confirmed
    assert "cannot confirm" in incident.summary.lower() or "incomplete" in incident.summary.lower() or "missing" in incident.uncertainty_note.lower()
