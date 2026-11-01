"""Upgraded baseline telemetry model for HopTrace v2.

Covers all 14 links across the 3-village topology.
Includes realistic noise simulation for continuous streaming.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .models import Measurement


# ── Documented baseline metrics per link ─────────────────────────────────────
BASELINE_TELEMETRY: Dict[str, Dict[str, float | bool]] = {
    # Village 1 — Rampur
    "L1":  {"latency_ms": 15.0,  "packet_loss_pct": 0.0, "throughput_mbps": 100.0, "connectivity_ok": True},
    "L2":  {"latency_ms":  2.0,  "packet_loss_pct": 0.0, "throughput_mbps":  80.0, "connectivity_ok": True},
    "L3":  {"latency_ms": 25.0,  "packet_loss_pct": 0.5, "throughput_mbps":  35.0, "connectivity_ok": True},
    "L4":  {"latency_ms":  3.0,  "packet_loss_pct": 0.0, "throughput_mbps":  50.0, "connectivity_ok": True},
    "L5":  {"latency_ms":  5.0,  "packet_loss_pct": 0.0, "throughput_mbps":  60.0, "connectivity_ok": True},
    # Village 2 — Bhatpur
    "L6":  {"latency_ms":  2.0,  "packet_loss_pct": 0.0, "throughput_mbps":  80.0, "connectivity_ok": True},
    "L7":  {"latency_ms": 12.0,  "packet_loss_pct": 0.2, "throughput_mbps":  40.0, "connectivity_ok": True},
    "L8":  {"latency_ms":  2.0,  "packet_loss_pct": 0.0, "throughput_mbps":  38.0, "connectivity_ok": True},
    "L9":  {"latency_ms":  3.0,  "packet_loss_pct": 0.0, "throughput_mbps":  35.0, "connectivity_ok": True},
    "L10": {"latency_ms":  3.0,  "packet_loss_pct": 0.0, "throughput_mbps":  35.0, "connectivity_ok": True},
    # Village 3 — Daulatpur
    "L11": {"latency_ms":  2.0,  "packet_loss_pct": 0.0, "throughput_mbps":  80.0, "connectivity_ok": True},
    "L12": {"latency_ms": 30.0,  "packet_loss_pct": 0.8, "throughput_mbps":  28.0, "connectivity_ok": True},
    "L13": {"latency_ms":  3.0,  "packet_loss_pct": 0.0, "throughput_mbps":  26.0, "connectivity_ok": True},
    "L14": {"latency_ms":  3.0,  "packet_loss_pct": 0.0, "throughput_mbps":  26.0, "connectivity_ok": True},
}

# Severity scaling factors for degradation scenarios
SEVERITY_FACTORS = {
    "low":    {"latency_delta_ms": 35.0,  "packet_loss_delta_pct": 5.0,  "throughput_multiplier": 0.70},
    "medium": {"latency_delta_ms": 90.0,  "packet_loss_delta_pct": 15.0, "throughput_multiplier": 0.40},
    "high":   {"latency_delta_ms": 175.0, "packet_loss_delta_pct": 25.0, "throughput_multiplier": 0.15},
}

# Upstream gateway link (the single fiber backhaul from PoP to R1)
GATEWAY_LINK_ID = "L1"
INTERIOR_LINK_IDS = ["L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11", "L12", "L13", "L14"]

# Noise amplitude for realistic streaming (±%)
_LATENCY_NOISE_PCT = 0.06    # ±6% jitter on latency
_LOSS_NOISE_ABS = 0.2        # ±0.2% absolute noise on packet loss
_TP_NOISE_PCT = 0.04         # ±4% throughput variation


class SimulatedTelemetryGenerator:
    """Produces deterministic simulated telemetry for laboratory scenarios.

    In streaming mode (with_noise=True), adds realistic small-amplitude
    noise to baseline values so the WebSocket feed looks live.
    """

    def __init__(
        self,
        baseline_metrics: Optional[Dict[str, Dict[str, float | bool]]] = None,
        seed: Optional[int] = None,
    ) -> None:
        self.baselines = baseline_metrics or BASELINE_TELEMETRY
        self._rng = random.Random(seed)  # seeded for reproducible streaming noise

    def _add_noise(self, value: float, pct: float, abs_noise: float = 0.0) -> float:
        """Add Gaussian-like noise bounded by pct of value or abs_noise."""
        noise = self._rng.gauss(0, pct * value + abs_noise)
        return max(0.0, value + noise)

    def generate_baseline_with_noise(self) -> List[Measurement]:
        """Generate baseline measurements with small realistic noise — for streaming."""
        ts = datetime.now(timezone.utc).isoformat()
        measurements = []
        for link_id, base in self.baselines.items():
            base_lat = float(base["latency_ms"])
            base_loss = float(base["packet_loss_pct"])
            base_tp = float(base["throughput_mbps"])
            measurements.append(Measurement(
                component_id=link_id,
                timestamp_utc=ts,
                latency_ms=round(self._add_noise(base_lat, _LATENCY_NOISE_PCT), 2),
                packet_loss_pct=round(max(0.0, self._add_noise(base_loss, 0.3, _LOSS_NOISE_ABS)), 2),
                throughput_mbps=round(self._add_noise(base_tp, _TP_NOISE_PCT), 2),
                connectivity_ok=True,
                data_source="simulated",
            ))
        return measurements

    def generate_measurements(
        self,
        scenario: str = "baseline",
        target_link_id: Optional[str] = None,
        target_node_id: Optional[str] = None,
        severity: str = "medium",
        missing_link_ids: Optional[List[str]] = None,
        ambiguous_link_ids: Optional[List[str]] = None,
        timestamp: Optional[str] = None,
        with_noise: bool = False,
    ) -> List[Measurement]:
        """Generates deterministic measurements based on scenario specifications.

        Supported scenarios:
        - baseline            : All links healthy.
        - degrade_link        : Target link degrades (latency ↑, loss ↑, tp ↓).
        - access_point_failure: Incoming link to target AP fails completely.
        - upstream_failure    : Gateway fiber (L1) fails; interior links show blackout.
        - ambiguous_fault     : Two links degrade equally.
        - cascade_fault       : Two adjacent links degrade (NEW in v2).
        - flapping_link       : Target link alternates up/down rapidly (NEW in v2).
        - missing_measurements: Selected links have null telemetry.
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        missing_set = set(missing_link_ids or [])
        measurements: List[Measurement] = []

        factors = SEVERITY_FACTORS.get(severity, SEVERITY_FACTORS["medium"])
        degraded_links: Dict[str, Dict] = {}

        # --- Determine which links to degrade ---
        if scenario == "degrade_link" and target_link_id:
            degraded_links[target_link_id] = factors

        elif scenario == "ambiguous_fault":
            links_to_degrade = ambiguous_link_ids or ["L2", "L3"]
            for lid in links_to_degrade:
                degraded_links[lid] = factors

        elif scenario == "cascade_fault":
            # Cascade: two adjacent links in the same path degrade simultaneously
            # Defaults to L3 + L7 (both PtP wireless hops, serving different villages)
            cascade_targets = ambiguous_link_ids or ["L3", "L7"]
            for lid in cascade_targets:
                degraded_links[lid] = factors

        elif scenario == "flapping_link":
            # Flapping: target link alternates; simulate 50% loss + degraded TP
            if target_link_id:
                degraded_links[target_link_id] = {
                    "latency_delta_ms": 20.0,
                    "packet_loss_delta_pct": 45.0,
                    "throughput_multiplier": 0.30,
                    "_flapping": True,
                }

        for link_id, base in self.baselines.items():
            if link_id in missing_set:
                measurements.append(Measurement(
                    component_id=link_id, timestamp_utc=ts,
                    latency_ms=None, packet_loss_pct=None,
                    throughput_mbps=None, connectivity_ok=False,
                    data_source="simulated",
                ))
                continue

            # Upstream failure: L1 down, all interior links blackout
            if scenario == "upstream_failure":
                if link_id == GATEWAY_LINK_ID:
                    measurements.append(Measurement(
                        component_id=link_id, timestamp_utc=ts,
                        latency_ms=None, packet_loss_pct=100.0,
                        throughput_mbps=0.0, connectivity_ok=False,
                        data_source="simulated",
                    ))
                else:
                    measurements.append(Measurement(
                        component_id=link_id, timestamp_utc=ts,
                        latency_ms=None, packet_loss_pct=100.0,
                        throughput_mbps=0.0, connectivity_ok=True,
                        data_source="simulated",
                    ))
                continue

            # Access point failure: incoming link to the AP fails
            if scenario == "access_point_failure" and target_node_id:
                ap_incoming = {
                    "AP1": "L4", "AP2": "L5",
                    "AP3": "L9", "AP4": "L10",
                    "AP5": "L13", "AP6": "L14",
                }
                failing_link = ap_incoming.get(target_node_id)
                if failing_link and link_id == failing_link:
                    measurements.append(Measurement(
                        component_id=link_id, timestamp_utc=ts,
                        latency_ms=None, packet_loss_pct=100.0,
                        throughput_mbps=0.0, connectivity_ok=False,
                        data_source="simulated",
                    ))
                    continue

            # Degraded / cascade / flapping link
            if link_id in degraded_links:
                f = degraded_links[link_id]
                base_lat = float(base["latency_ms"])
                base_loss = float(base["packet_loss_pct"])
                base_tp = float(base["throughput_mbps"])

                is_flapping = f.get("_flapping", False)
                conn_ok = not is_flapping  # flapping links show connectivity_ok=False

                m = Measurement(
                    component_id=link_id, timestamp_utc=ts,
                    latency_ms=round(base_lat + f["latency_delta_ms"], 2),
                    packet_loss_pct=round(base_loss + f["packet_loss_delta_pct"], 2),
                    throughput_mbps=round(base_tp * f["throughput_multiplier"], 2),
                    connectivity_ok=conn_ok,
                    data_source="simulated",
                )
                measurements.append(m)
            else:
                # Healthy baseline (optionally with noise)
                base_lat = float(base["latency_ms"])
                base_loss = float(base["packet_loss_pct"])
                base_tp = float(base["throughput_mbps"])
                if with_noise:
                    base_lat = round(self._add_noise(base_lat, _LATENCY_NOISE_PCT), 2)
                    base_loss = round(max(0.0, self._add_noise(base_loss, 0.3, _LOSS_NOISE_ABS)), 2)
                    base_tp = round(self._add_noise(base_tp, _TP_NOISE_PCT), 2)
                measurements.append(Measurement(
                    component_id=link_id, timestamp_utc=ts,
                    latency_ms=base_lat,
                    packet_loss_pct=base_loss,
                    throughput_mbps=base_tp,
                    connectivity_ok=bool(base["connectivity_ok"]),
                    data_source="simulated",
                ))

        return measurements
