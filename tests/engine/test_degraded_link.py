"""Automated tests for the degraded intermediate-link scenario."""

import inspect
import pytest
from backend.app.engine import (
    SimulatedTelemetryGenerator,
    diagnose,
    get_default_topology,
    run_scenario,
    get_incident_details,
    BASELINE_TELEMETRY,
)


@pytest.mark.parametrize("target_link", ["L3", "L2", "L1", "L4", "L5"])
@pytest.mark.parametrize("severity", ["low", "medium", "high"])
def test_degraded_link_identification(target_link: str, severity: str):
    """Tests that the diagnostic engine correctly infers the degraded link.

    CRITICAL VALIDATION RULE:
    The target_link is retained ONLY by the test harness for final evaluation.
    The diagnose() function receives solely measurements, baselines, and topology.
    """
    generator = SimulatedTelemetryGenerator()
    measurements = generator.generate_measurements(
        scenario="degrade_link",
        target_link_id=target_link,
        severity=severity,
    )
    topology = get_default_topology()

    # Verify that diagnose does NOT accept target_link or expected_fault
    sig = inspect.signature(diagnose)
    assert "target_link" not in sig.parameters
    assert "target_link_id" not in sig.parameters
    assert "expected_fault" not in sig.parameters

    # Run diagnosis strictly on observations
    incident = diagnose(measurements=measurements, topology=topology)

    # Evaluation layer comparison
    assert incident.suspected_component_id == target_link
    assert incident.suspected_component_type == "link"
    assert incident.status == "open"
    assert incident.diagnostic_score is not None and incident.diagnostic_score >= 0.10
    assert len(incident.evidence) > 0

    # Verify that evidence contains observed anomalies exceeding baselines
    base_metrics = BASELINE_TELEMETRY[target_link]
    for ev in incident.evidence:
        if ev.metric == "packet_loss_pct":
            assert ev.observed_value > base_metrics["packet_loss_pct"]
        elif ev.metric == "latency_ms":
            assert ev.observed_value > base_metrics["latency_ms"]
        elif ev.metric == "throughput_mbps":
            assert ev.observed_value < base_metrics["throughput_mbps"]


def test_degraded_link_via_facade():
    """Tests degraded link scenario executed through the engine facade."""
    expected_fault = "L3"  # Wireless PtP link across terrain
    res = run_scenario(
        scenario="degrade_link",
        target_link_id=expected_fault,
        severity="high",
        force_in_memory=True,
    )

    assert res.run_id is not None
    assert res.incident_id is not None

    incident = get_incident_details(res.incident_id)
    assert incident is not None
    assert incident.suspected_component_id == expected_fault
    assert incident.suspected_component_type == "link"
    assert "L3" in incident.summary
    assert incident.confidence_score is not None and incident.confidence_score >= 0.70
