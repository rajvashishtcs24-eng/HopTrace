"""Automated tests for ambiguous telemetry evidence."""

import pytest
from backend.app.engine import (
    SimulatedTelemetryGenerator,
    diagnose,
    get_default_topology,
    run_scenario,
    get_incident_details,
)


def test_ambiguous_evidence_reports_uncertainty():
    """Validates that when two links show similar degradation, ambiguity is reported.

    Do not invent a probability of correctness. If available evidence is
    ambiguous, report that limitation in uncertainty_note.
    """
    generator = SimulatedTelemetryGenerator()
    # Both L2 and L3 degraded with identical severity
    measurements = generator.generate_measurements(
        scenario="ambiguous_fault",
        ambiguous_link_ids=["L2", "L3"],
        severity="medium",
    )
    topology = get_default_topology()

    incident = diagnose(measurements=measurements, topology=topology)

    assert incident.status == "open"
    assert incident.suspected_component_id in ["L2", "L3"]
    # Ambiguity note MUST be present and name both candidate links
    assert incident.uncertainty_note is not None
    assert "Ambiguous evidence" in incident.uncertainty_note
    assert "L2" in incident.uncertainty_note
    assert "L3" in incident.uncertainty_note

    # Confidence score must reflect ambiguity, not false certainty
    assert incident.confidence_score is not None
    assert incident.confidence_score <= 0.60


def test_ambiguous_scenario_via_facade():
    """Validates ambiguous scenario run via engine facade."""
    res = run_scenario(
        scenario="ambiguous_fault",
        ambiguous_link_ids=["L2", "L3"],
        severity="medium",
        force_in_memory=True,
    )
    assert res.incident_id is not None

    incident = get_incident_details(res.incident_id)
    assert incident is not None
    assert incident.uncertainty_note is not None
    assert "ambiguity detected" in incident.summary.lower()
