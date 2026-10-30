"""
Simulated topology provider.

Used when `TOPOLOGY_PROVIDER=simulated` (the default for local development and
demos without a live Neo4j instance).

IMPORTANT: data_source is always "simulated" here.  This data must never be
labelled as "measured" or presented as real network observations.

The topology models a small ISP last-mile network:
  GW1 (upstream gateway)
    └─ R1 (core router)
         ├─ WB1 (wireless bridge, feeder link to cluster A)
         │    └─ AP1 (access point serving subscribers)
         └─ WB2 (wireless bridge, feeder link to cluster B)
              └─ AP2 (access point serving subscribers)
"""
from __future__ import annotations

from app.providers.base import TopologyProvider
from app.schemas.topology import TopologyLink, TopologyNode, TopologyResponse


class SimulatedTopologyProvider(TopologyProvider):
    """Returns a fixed simulated topology.  data_source is always 'simulated'."""

    def get_topology(self) -> TopologyResponse:
        nodes: list[TopologyNode] = [
            TopologyNode(id="GW1", type="gateway",       label="Upstream Gateway",          status="healthy"),
            TopologyNode(id="R1",  type="router",         label="Core Router",               status="healthy"),
            TopologyNode(id="WB1", type="wireless_bridge",label="Wireless Bridge – Cluster A",status="healthy"),
            TopologyNode(id="WB2", type="wireless_bridge",label="Wireless Bridge – Cluster B",status="healthy"),
            TopologyNode(id="AP1", type="access_point",   label="Access Point A1",           status="healthy"),
            TopologyNode(id="AP2", type="access_point",   label="Access Point B1",           status="healthy"),
        ]

        links: list[TopologyLink] = [
            TopologyLink(
                id="L1", source="GW1", target="R1",
                status="healthy",
                latency_ms=5.0, packet_loss_pct=0.0, throughput_mbps=1000.0,
            ),
            TopologyLink(
                id="L2", source="R1", target="WB1",
                status="healthy",
                latency_ms=12.0, packet_loss_pct=0.1, throughput_mbps=200.0,
            ),
            TopologyLink(
                id="L3", source="R1", target="WB2",
                status="healthy",
                latency_ms=14.0, packet_loss_pct=0.1, throughput_mbps=200.0,
            ),
            TopologyLink(
                id="L4", source="WB1", target="AP1",
                status="healthy",
                latency_ms=20.0, packet_loss_pct=0.0, throughput_mbps=40.0,
            ),
            TopologyLink(
                id="L5", source="WB2", target="AP2",
                status="healthy",
                # throughput_mbps deliberately null to demonstrate nullable fields
                latency_ms=22.0, packet_loss_pct=0.0, throughput_mbps=None,
            ),
        ]

        return TopologyResponse(nodes=nodes, links=links, data_source="simulated")
