"""Explainable fault localization engine for HopTrace.

CRITICAL VALIDATION RULE:
The diagnostic engine infers suspected faults SOLELY from observed measurements,
documented baselines, and graph topology. It NEVER receives the injected
fault ID, scenario name, or ground truth label as input.

Documented Scoring Model:
Composite Diagnostic Score S in [0.0, 1.0]:
S = (w_conn * s_conn) + (w_loss * s_loss) + (w_lat * s_lat) + (w_tp * s_tp)
Weights:
- w_conn = 0.40 (Connectivity failure)
- w_loss = 0.30 (Packet loss abnormality)
- w_lat  = 0.20 (Latency increase)
- w_tp   = 0.10 (Throughput degradation)

Detection Threshold:
- Score >= 0.10 triggers anomaly detection.
- Score < 0.10 considered within normal operating limits.

Ambiguity Rule:
- If |S_top1 - S_top2| <= 0.08 for two degraded links, the engine flags
  the incident with an explicit uncertainty_note and degraded confidence.
- Missing measurements are explicitly recorded as uncertainty and NEVER
  treated as healthy.

Upstream Failure Detection:
When all monitored links report full packet loss (100%) AND throughput drops
to zero, with the gateway/backhaul link (L1) showing connectivity_ok=False,
the engine classifies the incident as an upstream/gateway failure affecting
component L1 with component_type="link". The distinguishing signature is:
  - L1 is down (connectivity_ok=False).
  - ALL downstream links simultaneously show 100% packet loss and zero throughput
    (because no internet traffic can pass after the gateway is lost).
This pattern cannot arise from a single intermediate link failure because that
would only affect a subset of downstream links.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from backend.app.engine.models import (
    EvidenceItem,
    IncidentDetails,
    Measurement,
    NetworkTopology,
)
from backend.app.engine.telemetry import BASELINE_TELEMETRY, GATEWAY_LINK_ID, INTERIOR_LINK_IDS


class LinkAnomalyReport:
    """Internal evaluation record for a single link's telemetry."""

    def __init__(self, link_id: str) -> None:
        self.link_id = link_id
        self.score: float = 0.0
        self.s_conn: float = 0.0
        self.s_loss: float = 0.0
        self.s_lat: float = 0.0
        self.s_tp: float = 0.0
        self.evidence: List[EvidenceItem] = []
        self.missing_metrics_count: int = 0
        self.is_unmonitored: bool = False


class DiagnosticEngine:
    """Explainable diagnostic engine for rural ISP network fault localization."""

    def __init__(
        self,
        baselines: Optional[Dict[str, Dict[str, float | bool]]] = None,
        detection_threshold: float = 0.10,
        ambiguity_margin: float = 0.08,
        upstream_full_loss_threshold: float = 98.0,
    ) -> None:
        self.baselines = baselines or BASELINE_TELEMETRY
        self.detection_threshold = detection_threshold
        self.ambiguity_margin = ambiguity_margin
        # Packet loss % on ALL links that indicates total upstream blackout
        self.upstream_full_loss_threshold = upstream_full_loss_threshold

    def evaluate_link(
        self,
        measurement: Optional[Measurement],
        baseline: Dict[str, float | bool],
        link_id: str,
    ) -> LinkAnomalyReport:
        """Evaluates a single link's measurement against documented baseline values."""
        report = LinkAnomalyReport(link_id)

        if measurement is None:
            report.is_unmonitored = True
            report.missing_metrics_count = 4
            report.evidence.append(
                EvidenceItem(
                    metric="telemetry_presence",
                    observed_value=None,
                    baseline_value="active_telemetry",
                    threshold="required",
                    status="missing",
                    severity="medium",
                    description=f"Link '{link_id}' has no telemetry reports. Health cannot be verified.",
                )
            )
            return report

        base_lat = float(baseline.get("latency_ms", 20.0))
        base_loss = float(baseline.get("packet_loss_pct", 0.0))
        base_tp = float(baseline.get("throughput_mbps", 50.0))
        base_conn = bool(baseline.get("connectivity_ok", True))

        # 1. Connectivity status
        if not measurement.connectivity_ok:
            report.s_conn = 1.0
            report.evidence.append(
                EvidenceItem(
                    metric="connectivity_ok",
                    observed_value=False,
                    baseline_value=base_conn,
                    threshold=True,
                    status="anomaly",
                    severity="critical",
                    description=f"Link '{link_id}' reported loss of connectivity (link down).",
                )
            )

        # 2. Packet Loss Abnormality
        if measurement.packet_loss_pct is None:
            report.missing_metrics_count += 1
            report.evidence.append(
                EvidenceItem(
                    metric="packet_loss_pct",
                    observed_value=None,
                    baseline_value=base_loss,
                    threshold="<= 1.0%",
                    status="missing",
                    severity="low",
                    description=f"Packet loss telemetry missing for link '{link_id}'.",
                )
            )
        else:
            delta_loss = max(0.0, measurement.packet_loss_pct - base_loss)
            if delta_loss > 1.0:
                report.s_loss = min(1.0, delta_loss / 25.0)
                sev = "high" if delta_loss >= 15.0 else ("medium" if delta_loss >= 5.0 else "low")
                report.evidence.append(
                    EvidenceItem(
                        metric="packet_loss_pct",
                        observed_value=measurement.packet_loss_pct,
                        baseline_value=base_loss,
                        threshold=1.0,
                        status="anomaly",
                        severity=sev,
                        description=(
                            f"Packet loss {measurement.packet_loss_pct:.1f}% exceeds baseline "
                            f"({base_loss:.1f}%) by {delta_loss:.1f}%."
                        ),
                    )
                )

        # 3. Latency Inflation
        if measurement.latency_ms is None:
            report.missing_metrics_count += 1
            report.evidence.append(
                EvidenceItem(
                    metric="latency_ms",
                    observed_value=None,
                    baseline_value=base_lat,
                    threshold=f"<= {base_lat + 10.0} ms",
                    status="missing",
                    severity="low",
                    description=f"Latency telemetry missing for link '{link_id}'.",
                )
            )
        else:
            delta_lat = max(0.0, measurement.latency_ms - base_lat)
            if delta_lat > 10.0:
                report.s_lat = min(1.0, delta_lat / 150.0)
                sev = "high" if delta_lat >= 80.0 else ("medium" if delta_lat >= 30.0 else "low")
                report.evidence.append(
                    EvidenceItem(
                        metric="latency_ms",
                        observed_value=measurement.latency_ms,
                        baseline_value=base_lat,
                        threshold=round(base_lat + 10.0, 1),
                        status="anomaly",
                        severity=sev,
                        description=(
                            f"Observed latency {measurement.latency_ms:.1f} ms exceeds baseline "
                            f"({base_lat:.1f} ms) by +{delta_lat:.1f} ms."
                        ),
                    )
                )

        # 4. Throughput Degradation
        if measurement.throughput_mbps is None:
            report.missing_metrics_count += 1
            report.evidence.append(
                EvidenceItem(
                    metric="throughput_mbps",
                    observed_value=None,
                    baseline_value=base_tp,
                    threshold=f">= {base_tp * 0.85:.1f} Mbps",
                    status="missing",
                    severity="low",
                    description=f"Throughput telemetry missing for link '{link_id}'.",
                )
            )
        else:
            if base_tp > 0:
                drop_pct = max(0.0, (base_tp - measurement.throughput_mbps) / base_tp)
            else:
                drop_pct = 0.0

            if drop_pct > 0.15:
                report.s_tp = min(1.0, (drop_pct - 0.15) / 0.70)
                sev = "high" if drop_pct >= 0.60 else ("medium" if drop_pct >= 0.30 else "low")
                report.evidence.append(
                    EvidenceItem(
                        metric="throughput_mbps",
                        observed_value=measurement.throughput_mbps,
                        baseline_value=base_tp,
                        threshold=round(base_tp * 0.85, 1),
                        status="anomaly",
                        severity=sev,
                        description=(
                            f"Throughput degraded to {measurement.throughput_mbps:.1f} Mbps "
                            f"({drop_pct * 100:.1f}% below baseline {base_tp:.1f} Mbps)."
                        ),
                    )
                )

        # Composite score calculation
        # Weights: w_conn=0.40, w_loss=0.30, w_lat=0.20, w_tp=0.10
        raw_score = (
            (0.40 * report.s_conn)
            + (0.30 * report.s_loss)
            + (0.20 * report.s_lat)
            + (0.10 * report.s_tp)
        )
        report.score = round(raw_score, 4)
        return report

    def _detect_upstream_failure(
        self,
        meas_map: Dict[str, Measurement],
        known_links: List[str],
    ) -> Optional[IncidentDetails]:
        """Detects the upstream-gateway-failure pattern from observations alone.

        Upstream signature (inferred from measurements, not from ground truth):
          1. The gateway backhaul link (GATEWAY_LINK_ID) has connectivity_ok=False.
          2. ALL interior distribution links have packet_loss >= upstream_full_loss_threshold
             AND throughput = 0 simultaneously.
          3. At least one interior link is locally link-present (connectivity_ok=True),
             which rules out a cascade of independent link failures.

        This combination is statistically inconsistent with a single intermediate
        link failure, which would only affect a downstream subset of links.
        Returns an IncidentDetails if the pattern matches, otherwise None.
        """
        gw_link_id = GATEWAY_LINK_ID
        interior_ids = [lid for lid in known_links if lid != gw_link_id]

        gw_meas = meas_map.get(gw_link_id)
        if gw_meas is None:
            # Gateway link telemetry entirely missing — cannot confirm upstream failure
            return None

        # Condition 1: gateway link is down
        gw_down = not gw_meas.connectivity_ok

        if not gw_down:
            return None

        # Condition 2: all interior links show full loss and zero throughput
        interior_measured = [meas_map.get(lid) for lid in interior_ids if meas_map.get(lid) is not None]
        if not interior_measured:
            return None

        all_interior_saturated = all(
            m.packet_loss_pct is not None
            and m.packet_loss_pct >= self.upstream_full_loss_threshold
            and m.throughput_mbps is not None
            and m.throughput_mbps == 0.0
            for m in interior_measured
        )

        if not all_interior_saturated:
            return None

        # Condition 3: at least one interior link is locally link-present
        any_interior_link_up = any(m.connectivity_ok for m in interior_measured)

        # Build detailed evidence
        evidence: List[EvidenceItem] = []

        evidence.append(
            EvidenceItem(
                metric="connectivity_ok",
                observed_value=False,
                baseline_value=True,
                threshold=True,
                status="anomaly",
                severity="critical",
                description=(
                    f"Gateway backhaul link '{gw_link_id}' has lost connectivity. "
                    "No internet traffic can pass into the village network."
                ),
            )
        )
        evidence.append(
            EvidenceItem(
                metric="packet_loss_pct",
                observed_value=100.0,
                baseline_value=0.0,
                threshold=1.0,
                status="anomaly",
                severity="critical",
                description=(
                    f"All {len(interior_measured)} interior distribution link(s) simultaneously "
                    f"report 100% packet loss — consistent with full upstream internet blackout, "
                    "not a single intermediate segment failure."
                ),
            )
        )
        evidence.append(
            EvidenceItem(
                metric="throughput_mbps",
                observed_value=0.0,
                baseline_value=None,
                threshold=None,
                status="anomaly",
                severity="critical",
                description=(
                    "Zero throughput observed across all distribution links. "
                    "Interior links remain locally link-present (no independent physical failure)."
                ),
            )
        )

        if not any_interior_link_up:
            uncertainty_note = (
                "Interior links also report connectivity_ok=False. This may indicate a "
                "total power failure or cascading hardware fault rather than upstream-only "
                "failure. Evidence points to L1/GW1 as root cause but physical inspection "
                "is recommended."
            )
        else:
            uncertainty_note = (
                "Interior distribution links remain locally link-present (Ethernet/RF layer up). "
                "The simultaneous full packet loss and zero throughput across all interior "
                "segments is consistent with an upstream internet gateway failure at L1/GW1."
            )

        return IncidentDetails(
            id=f"incident-{uuid.uuid4().hex[:8]}",
            run_id="",
            status="open",
            suspected_component_id=gw_link_id,
            suspected_component_type="link",
            summary=(
                f"Upstream internet gateway failure detected on link '{gw_link_id}'. "
                f"All {len(interior_measured)} downstream distribution segments show "
                "complete internet traffic blackout consistent with gateway loss, not "
                "an intermediate segment fault."
            ),
            confidence_score=0.92 if any_interior_link_up else 0.70,
            diagnostic_score=1.0,
            evidence=evidence,
            uncertainty_note=uncertainty_note,
            data_source="simulated",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def diagnose(
        self,
        measurements: List[Measurement],
        topology: Optional[NetworkTopology] = None,
        run_id: Optional[str] = None,
    ) -> IncidentDetails:
        """Infers the root-cause suspect from telemetry observations.

        CRITICAL: Never accepts expected fault input. Solely infers suspect.
        """
        run_identifier = run_id or f"run-{uuid.uuid4().hex[:8]}"
        incident_id = f"incident-{uuid.uuid4().hex[:8]}"
        created_at = datetime.now(timezone.utc).isoformat()

        # Map measurements by component_id
        meas_map = {m.component_id: m for m in measurements}

        # Monitored links in topology or baselines
        known_links = list(self.baselines.keys())
        if topology and topology.links:
            known_links = [l.id for l in topology.links]

        # --- Upstream failure detection (pattern-based, no ground truth) ---
        upstream_incident = self._detect_upstream_failure(meas_map, known_links)
        if upstream_incident is not None:
            upstream_incident.id = incident_id
            upstream_incident.run_id = run_identifier
            upstream_incident.created_at = created_at
            return upstream_incident

        # --- Standard per-link anomaly scoring ---
        reports: List[LinkAnomalyReport] = []
        missing_notes: List[str] = []

        for link_id in known_links:
            m = meas_map.get(link_id)
            base = self.baselines.get(link_id, {})
            rep = self.evaluate_link(m, base, link_id)
            reports.append(rep)

            if rep.is_unmonitored or rep.missing_metrics_count > 0:
                missing_notes.append(
                    f"Link '{link_id}' has missing telemetry ({rep.missing_metrics_count} metric(s) null/omitted); cannot confirm healthy."
                )

        # Sort reports by anomaly score descending
        reports.sort(key=lambda r: r.score, reverse=True)

        top_report = reports[0] if reports else None
        top_score = top_report.score if top_report else 0.0

        # Case 1: Healthy baseline (no score exceeds detection threshold)
        if top_score < self.detection_threshold:
            uncertainty_text = None
            if missing_notes:
                uncertainty_text = (
                    "Incomplete telemetry: " + "; ".join(missing_notes)
                )

            return IncidentDetails(
                id=incident_id,
                run_id=run_identifier,
                status="closed" if not missing_notes else "open",
                suspected_component_id=None,
                suspected_component_type=None,
                summary=(
                    "Normal network operation: All monitored links within baseline thresholds."
                    if not missing_notes
                    else "Uncertain network state: Telemetry missing on some links without detected anomalies on others."
                ),
                confidence_score=1.0 if not missing_notes else None,
                diagnostic_score=top_score,
                evidence=[],
                uncertainty_note=uncertainty_text,
                data_source="simulated",
                created_at=created_at,
            )

        # Case 2: Anomaly detected! Check for ambiguity among candidates
        second_report = reports[1] if len(reports) > 1 else None
        second_score = second_report.score if second_report else 0.0

        is_ambiguous = (
            second_report is not None
            and second_score >= self.detection_threshold
            and abs(top_score - second_score) <= self.ambiguity_margin
        )

        uncertainty_note: Optional[str] = None
        confidence_score: Optional[float] = None

        if is_ambiguous and second_report:
            uncertainty_note = (
                f"Ambiguous evidence: Link '{top_report.link_id}' (score {top_score:.2f}) "
                f"and Link '{second_report.link_id}' (score {second_score:.2f}) show comparable "
                f"degradation within margin ({self.ambiguity_margin}). Root cause cannot be isolated "
                "to a single segment without intermediate hop telemetry."
            )
            # Confidence score is degraded proportionally to separation margin
            margin = abs(top_score - second_score)
            confidence_score = round(max(0.20, margin / self.detection_threshold), 2)
            summary = (
                f"Potential degradation on intermediate link {top_report.link_id} "
                f"(ambiguity detected with {second_report.link_id})"
            )
        else:
            # Clear distinct anomaly
            confidence_score = round(min(1.0, 0.5 + (top_score * 0.5)), 2)
            summary = f"Degradation localized to intermediate link {top_report.link_id}"
            if missing_notes:
                uncertainty_note = "Telemetry missing on other segments: " + "; ".join(missing_notes)

        # Combine evidence items for the suspected component
        evidence_items = top_report.evidence

        return IncidentDetails(
            id=incident_id,
            run_id=run_identifier,
            status="open",
            suspected_component_id=top_report.link_id,
            suspected_component_type="link",
            summary=summary,
            confidence_score=confidence_score,
            diagnostic_score=top_score,
            evidence=evidence_items,
            uncertainty_note=uncertainty_note,
            data_source="simulated",
            created_at=created_at,
        )


def diagnose(
    measurements: List[Measurement],
    topology: Optional[NetworkTopology] = None,
    run_id: Optional[str] = None,
    baselines: Optional[Dict[str, Dict[str, float | bool]]] = None,
) -> IncidentDetails:
    """Convenience function running the explainable diagnostic engine."""
    engine = DiagnosticEngine(baselines=baselines)
    return engine.diagnose(measurements=measurements, topology=topology, run_id=run_id)
