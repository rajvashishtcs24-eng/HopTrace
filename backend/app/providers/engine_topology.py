"""
Topology provider backed by the HopTrace graph engine.

Adapts the NetworkTopology produced by the engine facade (get_topology())
into the API schema TopologyResponse.
"""
from __future__ import annotations

from typing import Any

from app.engine.facade import get_topology
from app.providers.base import TopologyProvider, TopologyUnavailableError
from app.schemas.topology import (
    TopologyLink,
    TopologyNode,
    TopologyResponse,
)


def _normalize_status(status: Any) -> str:
    """Normalize status strings from the engine to the API contract.

    Engine uses 'down' for offline components, while API contract expects 'failed'.
    """
    raw = status.value if hasattr(status, "value") else str(status)
    val = raw.lower().strip()
    if val == "down":
        return "failed"
    if val in ("healthy", "degraded", "failed", "unknown"):
        return val
    return "unknown"


def _normalize_node_type(node_type: Any) -> str:
    """Normalize node types to documented types."""
    raw = node_type.value if hasattr(node_type, "value") else str(node_type)
    val = raw.lower().strip()
    if val in ("gateway", "router", "wireless_bridge", "access_point"):
        return val
    return "router"


class EngineTopologyProvider(TopologyProvider):
    """Topology provider backed by the HopTrace graph engine."""

    def get_topology(self) -> TopologyResponse:
        """Fetch topology from graph engine and adapt to API schema."""
        try:
            topology = get_topology()
        except Exception as exc:
            raise TopologyUnavailableError(
                f"Failed to retrieve topology from graph engine: {exc}"
            ) from exc

        if topology is None:
            raise TopologyUnavailableError("Engine returned empty topology.")

        try:
            nodes_raw = getattr(topology, "nodes", None) or []
            links_raw = getattr(topology, "links", None) or []

            nodes = [
                TopologyNode(
                    id=node.id,
                    type=_normalize_node_type(node.type),
                    label=node.label,
                    status=_normalize_status(node.status),
                )
                for node in nodes_raw
            ]

            links = [
                TopologyLink(
                    id=link.id,
                    source=link.source,
                    target=link.target,
                    status=_normalize_status(link.status),
                    latency_ms=link.latency_ms,
                    packet_loss_pct=link.packet_loss_pct,
                    throughput_mbps=link.throughput_mbps,
                )
                for link in links_raw
            ]

            data_source = (
                "measured"
                if str(getattr(topology, "data_source", "")).lower() == "measured"
                else "simulated"
            )

            return TopologyResponse(
                nodes=nodes,
                links=links,
                data_source=data_source,
            )
        except Exception as exc:
            raise TopologyUnavailableError(
                f"Failed to map engine topology to API schema: {exc}"
            ) from exc
