"""Time-series ring buffer and EWMA anomaly detection for HopTrace v2.

Each link maintains a circular buffer of the last N measurements.
The EWMA (Exponential Weighted Moving Average) layer computes:
  - Smoothed metric estimates
  - Deviation from smoothed baseline (Z-score style)
  - Risk score per link (0–100)
  - Trend direction: 'stable' | 'degrading' | 'recovering'

No external dependencies: pure Python collections.deque.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple


# EWMA smoothing factor (0 < α ≤ 1). Higher → more reactive.
EWMA_ALPHA: float = 0.30
# Number of past samples kept per link
BUFFER_SIZE: int = 50
# Soft-alert threshold: deviation > this σ signals early warning
SOFT_ALERT_SIGMA: float = 2.5
# Hard-alert threshold: deviation > this σ confirms anomaly
HARD_ALERT_SIGMA: float = 4.0
# Flapping: connectivity_ok toggles this many times in FLAP_WINDOW ticks
FLAP_COUNT_THRESHOLD: int = 3
FLAP_WINDOW: int = 20


@dataclass
class LinkSample:
    """A single telemetry snapshot for one link."""
    tick: int
    timestamp_utc: str
    latency_ms: Optional[float]
    packet_loss_pct: Optional[float]
    throughput_mbps: Optional[float]
    connectivity_ok: bool
    # Derived fields (filled by TimeSeriesStore after push)
    risk_score: float = 0.0
    trend: str = "stable"          # stable | degrading | recovering
    alert_level: str = "normal"    # normal | warning | critical


@dataclass
class LinkState:
    """Running EWMA state for a single link."""
    link_id: str
    buffer: Deque[LinkSample] = field(default_factory=lambda: deque(maxlen=BUFFER_SIZE))

    # EWMA smoothed values
    ewma_latency: Optional[float] = None
    ewma_loss: Optional[float] = None
    ewma_throughput: Optional[float] = None

    # Variance estimate (Welford online algorithm)
    _m2_latency: float = 0.0
    _m2_loss: float = 0.0
    _m2_throughput: float = 0.0
    _count: int = 0

    # Flap detection
    flap_count: int = 0
    _last_connectivity: Optional[bool] = None

    # Recent trend slope (computed over last 10 samples)
    trend: str = "stable"
    alert_level: str = "normal"
    risk_score: float = 0.0


class TimeSeriesStore:
    """Manages per-link time-series state with EWMA anomaly scoring.

    Thread-safety: single-threaded asyncio usage. No locking needed
    when accessed only from async event loop.
    """

    def __init__(
        self,
        baselines: Optional[Dict[str, Dict[str, Any]]] = None,
        ewma_alpha: float = EWMA_ALPHA,
        buffer_size: int = BUFFER_SIZE,
    ) -> None:
        from .telemetry import BASELINE_TELEMETRY
        self.baselines: Dict[str, Dict[str, Any]] = baselines or BASELINE_TELEMETRY
        self.alpha = ewma_alpha
        self._link_states: Dict[str, LinkState] = {}
        self._global_tick: int = 0

    def _get_or_create(self, link_id: str) -> LinkState:
        if link_id not in self._link_states:
            self._link_states[link_id] = LinkState(link_id=link_id)
        return self._link_states[link_id]

    def push(
        self,
        link_id: str,
        latency_ms: Optional[float],
        packet_loss_pct: Optional[float],
        throughput_mbps: Optional[float],
        connectivity_ok: bool,
        tick: Optional[int] = None,
    ) -> LinkSample:
        """Push a new measurement into the ring buffer and update EWMA state."""
        if tick is None:
            self._global_tick += 1
            tick = self._global_tick

        state = self._get_or_create(link_id)
        state._count += 1

        # --- EWMA update ---
        alpha = self.alpha

        def ewma_update(current: Optional[float], new_val: Optional[float]) -> Optional[float]:
            if new_val is None:
                return current
            if current is None:
                return new_val
            return alpha * new_val + (1 - alpha) * current

        state.ewma_latency = ewma_update(state.ewma_latency, latency_ms)
        state.ewma_loss = ewma_update(state.ewma_loss, packet_loss_pct)
        state.ewma_throughput = ewma_update(state.ewma_throughput, throughput_mbps)

        # --- Flap detection ---
        if state._last_connectivity is not None and connectivity_ok != state._last_connectivity:
            state.flap_count += 1
        state._last_connectivity = connectivity_ok

        # Decay flap count outside window
        if state._count % FLAP_WINDOW == 0:
            state.flap_count = max(0, state.flap_count - 1)

        # --- Risk score computation ---
        risk = self._compute_risk_score(link_id, state, latency_ms, packet_loss_pct, throughput_mbps, connectivity_ok)
        state.risk_score = risk

        # --- Trend computation ---
        trend = self._compute_trend(state)
        state.trend = trend

        # --- Alert level ---
        if not connectivity_ok or risk >= 75:
            alert_level = "critical"
        elif risk >= 45:
            alert_level = "warning"
        else:
            alert_level = "normal"
        state.alert_level = alert_level

        sample = LinkSample(
            tick=tick,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            latency_ms=latency_ms,
            packet_loss_pct=packet_loss_pct,
            throughput_mbps=throughput_mbps,
            connectivity_ok=connectivity_ok,
            risk_score=round(risk, 1),
            trend=trend,
            alert_level=alert_level,
        )
        state.buffer.append(sample)
        return sample

    def _compute_risk_score(
        self,
        link_id: str,
        state: LinkState,
        latency_ms: Optional[float],
        packet_loss_pct: Optional[float],
        throughput_mbps: Optional[float],
        connectivity_ok: bool,
    ) -> float:
        """Compute a 0–100 risk score for the link based on EWMA deviation from baseline."""
        base = self.baselines.get(link_id, {})
        base_lat = float(base.get("latency_ms", 20.0))
        base_loss = float(base.get("packet_loss_pct", 0.0))
        base_tp = float(base.get("throughput_mbps", 50.0))

        if not connectivity_ok:
            return 100.0

        score = 0.0

        # Packet loss contribution (weight 0.40)
        if packet_loss_pct is not None and packet_loss_pct > base_loss:
            delta = packet_loss_pct - base_loss
            # Normalize: 25% excess loss → max contribution
            loss_factor = min(1.0, delta / 25.0)
            score += 40.0 * loss_factor

        # Latency contribution (weight 0.30)
        if latency_ms is not None:
            ewma_lat = state.ewma_latency or base_lat
            deviation = max(0.0, latency_ms - ewma_lat)
            # 150ms above EWMA → max contribution
            lat_factor = min(1.0, deviation / 150.0)
            score += 30.0 * lat_factor

        # Throughput degradation (weight 0.20)
        if throughput_mbps is not None and base_tp > 0:
            ewma_tp = state.ewma_throughput or base_tp
            drop_ratio = max(0.0, (ewma_tp - throughput_mbps) / base_tp)
            tp_factor = min(1.0, max(0.0, (drop_ratio - 0.15) / 0.70))
            score += 20.0 * tp_factor

        # Flapping contribution (weight 0.10)
        flap_factor = min(1.0, state.flap_count / FLAP_COUNT_THRESHOLD)
        score += 10.0 * flap_factor

        return round(min(100.0, score), 1)

    def _compute_trend(self, state: LinkState) -> str:
        """Compute trend from the last 10 risk scores in the buffer."""
        recent = list(state.buffer)[-10:]
        if len(recent) < 4:
            return "stable"
        scores = [s.risk_score for s in recent]
        # Simple linear regression slope
        n = len(scores)
        x_mean = (n - 1) / 2.0
        y_mean = sum(scores) / n
        numerator = sum((i - x_mean) * (scores[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return "stable"
        slope = numerator / denominator
        if slope > 1.5:
            return "degrading"
        if slope < -1.5:
            return "recovering"
        return "stable"

    def get_state(self, link_id: str) -> Optional[LinkState]:
        return self._link_states.get(link_id)

    def get_all_link_ids(self) -> List[str]:
        return list(self._link_states.keys())

    def get_risk_snapshot(self) -> List[Dict[str, Any]]:
        """Return current risk score + trend for all tracked links."""
        result = []
        for link_id, state in self._link_states.items():
            result.append({
                "link_id": link_id,
                "risk_score": state.risk_score,
                "trend": state.trend,
                "alert_level": state.alert_level,
                "flap_count": state.flap_count,
                "ewma_latency_ms": round(state.ewma_latency, 2) if state.ewma_latency is not None else None,
                "ewma_loss_pct": round(state.ewma_loss, 2) if state.ewma_loss is not None else None,
                "ewma_throughput_mbps": round(state.ewma_throughput, 2) if state.ewma_throughput is not None else None,
            })
        return sorted(result, key=lambda x: x["risk_score"], reverse=True)

    def get_link_history(self, link_id: str, n: int = 50) -> List[Dict[str, Any]]:
        """Return last N samples for a link as serializable dicts."""
        state = self._link_states.get(link_id)
        if not state:
            return []
        samples = list(state.buffer)[-n:]
        return [
            {
                "tick": s.tick,
                "timestamp_utc": s.timestamp_utc,
                "latency_ms": s.latency_ms,
                "packet_loss_pct": s.packet_loss_pct,
                "throughput_mbps": s.throughput_mbps,
                "connectivity_ok": s.connectivity_ok,
                "risk_score": s.risk_score,
                "trend": s.trend,
                "alert_level": s.alert_level,
            }
            for s in samples
        ]

    def detect_cascade(self, threshold_risk: float = 60.0, window: int = 2) -> bool:
        """Return True if 2+ links simultaneously exceed risk threshold in last `window` ticks."""
        count = 0
        for state in self._link_states.values():
            recent = list(state.buffer)[-window:]
            if any(s.risk_score >= threshold_risk for s in recent):
                count += 1
            if count >= 2:
                return True
        return False

    def detect_flapping_links(self) -> List[str]:
        """Return link_ids where flap count exceeds FLAP_COUNT_THRESHOLD."""
        return [
            lid for lid, state in self._link_states.items()
            if state.flap_count >= FLAP_COUNT_THRESHOLD
        ]

    def push_measurements_batch(self, measurements: List[Any], tick: Optional[int] = None) -> None:
        """Push a list of Measurement objects from the telemetry generator."""
        if tick is None:
            self._global_tick += 1
            tick = self._global_tick
        for m in measurements:
            self.push(
                link_id=m.component_id,
                latency_ms=m.latency_ms,
                packet_loss_pct=m.packet_loss_pct,
                throughput_mbps=m.throughput_mbps,
                connectivity_ok=m.connectivity_ok,
                tick=tick,
            )


# Module-level singleton for use across the application
_ts_store_instance: Optional[TimeSeriesStore] = None


def get_time_series_store() -> TimeSeriesStore:
    global _ts_store_instance
    if _ts_store_instance is None:
        _ts_store_instance = TimeSeriesStore()
    return _ts_store_instance
