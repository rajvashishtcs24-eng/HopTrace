"""Automated tests validating evaluation separation and accuracy reporting.

CRITICAL VALIDATION RULE:
The diagnostic function must not receive the expected fault ID as an input.
It must infer the suspected link solely from observations, baseline, and
permitted topology information.
"""

import inspect
import pytest
from backend.app.engine import (
    DiagnosticEngine,
    SimulatedTelemetryGenerator,
    diagnose,
    get_default_topology,
)


def test_diagnostic_signature_does_not_accept_ground_truth():
    """Validates that neither diagnose nor DiagnosticEngine accept ground truth fault inputs."""
    # 1. Check module-level diagnose()
    sig = inspect.signature(diagnose)
    forbidden_params = {
        "expected_fault",
        "target_link",
        "target_link_id",
        "target_node",
        "target_node_id",
        "fault_id",
        "scenario",
        "ground_truth",
    }
    for p in forbidden_params:
        assert p not in sig.parameters, f"Forbidden ground-truth parameter '{p}' found in diagnose()"

    # 2. Check DiagnosticEngine.diagnose()
    engine_sig = inspect.signature(DiagnosticEngine.diagnose)
    for p in forbidden_params:
        assert (
            p not in engine_sig.parameters
        ), f"Forbidden ground-truth parameter '{p}' found in DiagnosticEngine.diagnose()"


def test_empirical_accuracy_on_controlled_scenarios():
    """Runs a controlled evaluation matrix and computes empirical accuracy.

    Rule: Do not claim accuracy percentages until tests produce them.
    """
    generator = SimulatedTelemetryGenerator()
    topology = get_default_topology()

    test_cases = [
        # (target_link, severity)
        ("L1", "high"),
        ("L1", "medium"),
        ("L2", "high"),
        ("L2", "medium"),
        ("L3", "high"),
        ("L3", "medium"),
        ("L4", "high"),
        ("L4", "medium"),
        ("L5", "high"),
        ("L5", "medium"),
    ]

    total_tests = len(test_cases)
    correct_identifications = 0

    for expected_fault, severity in test_cases:
        # Generate telemetry with injected fault
        measurements = generator.generate_measurements(
            scenario="degrade_link",
            target_link_id=expected_fault,
            severity=severity,
        )

        # Diagnose ONLY from telemetry observations and topology
        incident = diagnose(measurements=measurements, topology=topology)

        # Evaluation layer checks prediction against expected_fault
        if incident.suspected_component_id == expected_fault:
            correct_identifications += 1

    accuracy_pct = (correct_identifications / total_tests) * 100.0
    # Empirically verified accuracy across all intermediate link degradation scenarios
    assert accuracy_pct == 100.0, f"Expected 100% accuracy, got {accuracy_pct}%"
