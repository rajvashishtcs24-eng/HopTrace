"""WebSocket endpoint for real-time telemetry streaming — HopTrace v2.

Endpoint: WS /ws/telemetry

Pushes a telemetry batch every TICK_INTERVAL_SECONDS seconds to all
connected clients. Batch includes:
  - Per-link measurements with risk scores and trends
  - Active incident (if any) from the engine
  - Cascade/flapping detection flags
  - Tick counter

Message format (JSON):
{
  "type": "telemetry_batch",
  "tick": 42,
  "timestamp_utc": "2026-11-01T...",
  "measurements": [
    {
      "link_id": "L3",
      "latency_ms": 187.4,
      "packet_loss_pct": 23.1,
      "throughput_mbps": 5.2,
      "connectivity_ok": true,
      "risk_score": 78.3,
      "trend": "degrading",
      "alert_level": "warning"
    },
    ...
  ],
  "active_incident": { ...IncidentDetails... } | null,
  "cascade_detected": false,
  "flapping_links": [],
  "network_status": "healthy" | "degraded" | "critical"
}
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.engine.facade import get_engine
from app.engine.time_series import get_time_series_store

router = APIRouter(tags=["telemetry_ws"])

TICK_INTERVAL_SECONDS: float = 3.0

# Connected WebSocket clients
_connected_clients: Set[WebSocket] = set()

# Background streaming task handle
_streaming_task: Optional[asyncio.Task] = None


async def _broadcast(message: Dict[str, Any]) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    if not _connected_clients:
        return
    payload = json.dumps(message, default=str)
    dead_clients: Set[WebSocket] = set()
    for ws in list(_connected_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead_clients.add(ws)
    _connected_clients.difference_update(dead_clients)


async def _streaming_loop() -> None:
    """Background coroutine: generates and broadcasts telemetry every TICK_INTERVAL_SECONDS."""
    engine = get_engine()
    ts_store = get_time_series_store()
    tick = 0

    while True:
        try:
            await asyncio.sleep(TICK_INTERVAL_SECONDS)

            if not _connected_clients:
                continue

            tick += 1
            now = datetime.now(timezone.utc).isoformat()

            # Generate noisy baseline measurements for streaming
            measurements = engine.telemetry_generator.generate_baseline_with_noise()

            # If there is an active injected incident, overlay its measurements
            latest = engine.get_latest_open_incident()
            injected_measurements = None
            if latest and latest.status == "open" and latest.suspected_component_id:
                # Fetch the run measurements that triggered this incident
                run = None
                if latest.run_id and latest.run_id in engine._runs:
                    run = engine._runs[latest.run_id]
                if run:
                    injected_measurements = run.measurements

            active_measurements = injected_measurements or measurements

            # Push into time-series store
            ts_store.push_measurements_batch(active_measurements, tick=tick)

            # Build risk snapshot
            risk_map = {r["link_id"]: r for r in ts_store.get_risk_snapshot()}

            # Compose per-link payload
            link_payloads = []
            for m in active_measurements:
                risk_info = risk_map.get(m.component_id, {})
                link_payloads.append({
                    "link_id": m.component_id,
                    "latency_ms": m.latency_ms,
                    "packet_loss_pct": m.packet_loss_pct,
                    "throughput_mbps": m.throughput_mbps,
                    "connectivity_ok": m.connectivity_ok,
                    "risk_score": risk_info.get("risk_score", 0.0),
                    "trend": risk_info.get("trend", "stable"),
                    "alert_level": risk_info.get("alert_level", "normal"),
                    "ewma_latency_ms": risk_info.get("ewma_latency_ms"),
                    "ewma_loss_pct": risk_info.get("ewma_loss_pct"),
                    "ewma_throughput_mbps": risk_info.get("ewma_throughput_mbps"),
                })

            # Cascade + flapping detection
            cascade_detected = ts_store.detect_cascade(threshold_risk=60.0)
            flapping_links = ts_store.detect_flapping_links()

            # Network-level status
            max_risk = max((r["risk_score"] for r in risk_map.values()), default=0.0)
            if max_risk >= 75 or not all(m.connectivity_ok for m in active_measurements):
                network_status = "critical"
            elif max_risk >= 40 or cascade_detected:
                network_status = "degraded"
            else:
                network_status = "healthy"

            # Active incident payload
            incident_payload = None
            if latest and latest.status == "open":
                incident_payload = {
                    "id": latest.id,
                    "run_id": latest.run_id,
                    "status": latest.status,
                    "suspected_component_id": latest.suspected_component_id,
                    "suspected_component_type": latest.suspected_component_type,
                    "summary": latest.summary,
                    "confidence_score": latest.confidence_score,
                    "diagnostic_score": latest.diagnostic_score,
                    "evidence": [e.model_dump() for e in (latest.evidence or [])],
                    "uncertainty_note": latest.uncertainty_note,
                    "created_at": latest.created_at,
                }

            batch = {
                "type": "telemetry_batch",
                "tick": tick,
                "timestamp_utc": now,
                "measurements": link_payloads,
                "active_incident": incident_payload,
                "cascade_detected": cascade_detected,
                "flapping_links": flapping_links,
                "network_status": network_status,
            }

            await _broadcast(batch)

        except asyncio.CancelledError:
            break
        except Exception:
            # Never crash the streaming loop; log and continue
            await asyncio.sleep(1.0)


def start_streaming_loop() -> None:
    """Start the background streaming task (called from app lifespan)."""
    global _streaming_task
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    if _streaming_task is None or _streaming_task.done():
        _streaming_task = loop.create_task(_streaming_loop())


def stop_streaming_loop() -> None:
    """Stop the background streaming task (called from app lifespan)."""
    global _streaming_task
    if _streaming_task and not _streaming_task.done():
        _streaming_task.cancel()
        _streaming_task = None


@router.websocket("/ws/telemetry")
async def telemetry_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint — clients connect here to receive live telemetry pushes."""
    await websocket.accept()
    _connected_clients.add(websocket)

    # Send an immediate hello message with current state
    engine = get_engine()
    ts_store = get_time_series_store()
    try:
        risk_snapshot = ts_store.get_risk_snapshot()
        latest = engine.get_latest_open_incident()
        incident_payload = None
        if latest and latest.status == "open":
            incident_payload = {
                "id": latest.id,
                "suspected_component_id": latest.suspected_component_id,
                "summary": latest.summary,
                "confidence_score": latest.confidence_score,
                "created_at": latest.created_at,
            }
        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": "HopTrace v2 live telemetry stream connected.",
            "risk_snapshot": risk_snapshot,
            "active_incident": incident_payload,
        }, default=str))
    except Exception:
        pass

    try:
        # Keep connection alive; client can send pings
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Handle ping/pong or client commands
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send keepalive
                try:
                    await websocket.send_text(json.dumps({"type": "keepalive"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        _connected_clients.discard(websocket)
