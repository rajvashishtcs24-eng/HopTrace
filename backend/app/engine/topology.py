"""Initial network topology definition for HopTrace Village Internet Business (T3.2).

Topology Structure:
- 1 Upstream Gateway (GW1 - PoP Fiber Termination)
- 3 Intermediate Devices:
    - R1: Core Village Router (Panchayat Tower)
    - WB1: Point-to-Point Wireless Bridge Transmitter (5GHz / 60GHz)
    - WB2: Point-to-Point Wireless Bridge Receiver (North Ward)
- 2 Access Points:
    - AP1: North Village Market Access Point
    - AP2: South Village Panchayat Access Point
- 5 Subscribers:
    - AP1 -> SUB101, SUB102
    - AP2 -> SUB201, SUB202, SUB203
- 5 Links:
    - L1: GW1 -> R1 (Fiber Backhaul)
    - L2: R1 -> WB1 (Tower to Bridge Tx)
    - L3: WB1 -> WB2 (Wireless PtP Link across terrain)
    - L4: WB2 -> AP1 (Bridge Rx to North AP)
    - L5: R1 -> AP2 (Tower to South AP)

Assumption:
Single-path routing: Subscribers do not have alternate redundant paths
unless explicitly represented in the graph.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from .models import (
    NetworkTopology,
    TopologyLink,
    TopologyNode,
    Subscriber,
    AffectedSubscriber,
)


def get_default_nodes() -> List[TopologyNode]:
    """Returns canonical node definitions for the village network."""
    return [
        TopologyNode(
            id="GW1",
            type="gateway",
            label="Upstream Gateway (Fiber PoP)",
            status="healthy",
            properties={"location": "Taluk Substation", "ip": "10.0.0.1"},
        ),
        TopologyNode(
            id="R1",
            type="router",
            label="Core Village Router (Tower)",
            status="healthy",
            properties={"location": "Village Water Tower", "ip": "10.0.1.1"},
        ),
        TopologyNode(
            id="WB1",
            type="wireless_bridge",
            label="PtP Bridge Tx (Tower)",
            status="healthy",
            properties={"location": "Village Water Tower", "frequency": "5GHz"},
        ),
        TopologyNode(
            id="WB2",
            type="wireless_bridge",
            label="PtP Bridge Rx (North Ward)",
            status="healthy",
            properties={"location": "North Hamlet Pole", "frequency": "5GHz"},
        ),
        TopologyNode(
            id="AP1",
            type="access_point",
            label="North Village Market AP",
            status="healthy",
            properties={"location": "Market Square", "coverage_radius_m": 300},
        ),
        TopologyNode(
            id="AP2",
            type="access_point",
            label="South Village Panchayat AP",
            status="healthy",
            properties={"location": "Gram Panchayat Bhawan", "coverage_radius_m": 250},
        ),
    ]


def get_default_links() -> List[TopologyLink]:
    """Returns canonical link definitions connecting devices."""
    return [
        TopologyLink(
            id="L1",
            source="GW1",
            target="R1",
            status="healthy",
            latency_ms=15.0,
            packet_loss_pct=0.0,
            throughput_mbps=100.0,
            properties={"medium": "fiber", "capacity_mbps": 100.0},
        ),
        TopologyLink(
            id="L2",
            source="R1",
            target="WB1",
            status="healthy",
            latency_ms=2.0,
            packet_loss_pct=0.0,
            throughput_mbps=80.0,
            properties={"medium": "ethernet", "capacity_mbps": 1000.0},
        ),
        TopologyLink(
            id="L3",
            source="WB1",
            target="WB2",
            status="healthy",
            latency_ms=25.0,
            packet_loss_pct=0.5,
            throughput_mbps=35.0,
            properties={"medium": "wireless_ptp", "distance_km": 3.2},
        ),
        TopologyLink(
            id="L4",
            source="WB2",
            target="AP1",
            status="healthy",
            latency_ms=3.0,
            packet_loss_pct=0.0,
            throughput_mbps=50.0,
            properties={"medium": "ethernet", "capacity_mbps": 1000.0},
        ),
        TopologyLink(
            id="L5",
            source="R1",
            target="AP2",
            status="healthy",
            latency_ms=5.0,
            packet_loss_pct=0.0,
            throughput_mbps=60.0,
            properties={"medium": "ethernet", "capacity_mbps": 1000.0},
        ),
    ]


def get_default_subscribers() -> List[Subscriber]:
    """Returns initial demo subscribers per access point."""
    return [
        # AP1 Subscribers
        Subscriber(
            id="SUB101",
            display_name="Ramesh Patel (Kishan Kirana)",
            access_point_id="AP1",
            plan="Basic",
            status="active",
            payment_status="paid",
            due_date="2026-11-01",
        ),
        Subscriber(
            id="SUB102",
            display_name="Gram Panchayat e-Seva Kendra",
            access_point_id="AP1",
            plan="Enterprise",
            status="active",
            payment_status="paid",
            due_date="2026-11-01",
        ),
        # AP2 Subscribers
        Subscriber(
            id="SUB201",
            display_name="Primary Health Centre (PHC)",
            access_point_id="AP2",
            plan="Community",
            status="active",
            payment_status="paid",
            due_date="2026-11-01",
        ),
        Subscriber(
            id="SUB202",
            display_name="Govt Secondary School",
            access_point_id="AP2",
            plan="Community",
            status="active",
            payment_status="paid",
            due_date="2026-11-01",
        ),
        Subscriber(
            id="SUB203",
            display_name="Manoj CSC Center",
            access_point_id="AP2",
            plan="Basic",
            status="active",
            payment_status="paid",
            due_date="2026-11-01",
        ),
    ]


def get_default_topology() -> NetworkTopology:
    """Returns the complete default NetworkTopology object."""
    return NetworkTopology(
        nodes=get_default_nodes(),
        links=get_default_links(),
        data_source="simulated",
    )


class InMemoryTopologyGraph:
    """In-memory representation of the graph topology for zero-dependency unit tests.

    Mirrors the exact graph semantics and downstream dependency logic of Neo4j.
    """

    def __init__(
        self,
        nodes: Optional[List[TopologyNode]] = None,
        links: Optional[List[TopologyLink]] = None,
        subscribers: Optional[List[Subscriber]] = None,
    ) -> None:
        self.nodes: Dict[str, TopologyNode] = {
            n.id: n for n in (nodes if nodes is not None else get_default_nodes())
        }
        self.links: Dict[str, TopologyLink] = {
            l.id: l for l in (links if links is not None else get_default_links())
        }
        self.subscribers: Dict[str, Subscriber] = {
            s.id: s for s in (subscribers if subscribers is not None else get_default_subscribers())
        }

    def get_downstream_access_points(self, start_node_id: str) -> List[str]:
        """Finds all access point IDs reachable downstream from start_node_id along links."""
        visited_nodes = set()
        queue = [start_node_id]
        reachable_aps = []

        while queue:
            current = queue.pop(0)
            if current in visited_nodes:
                continue
            visited_nodes.add(current)

            node = self.nodes.get(current)
            if node and node.type == "access_point":
                reachable_aps.append(current)

            # Traverse outgoing links
            for link in self.links.values():
                if link.source == current and link.target not in visited_nodes:
                    queue.append(link.target)

        return reachable_aps

    def get_affected_subscribers(
        self,
        suspected_component_id: str,
        component_type: str = "link",
    ) -> List[AffectedSubscriber]:
        """Calculates affected subscribers depending on the suspected component.

        Assumption:
        Single-path routing. Downstream reachability from the target of the
        suspected link (or the node itself) determines which APs lose backhaul.
        """
        target_aps: List[str] = []

        if component_type == "link" or suspected_component_id in self.links:
            link = self.links.get(suspected_component_id)
            if not link:
                return []
            # All APs reachable from the target of this link
            target_aps = self.get_downstream_access_points(link.target)

        elif component_type in ("node", "access_point", "router", "wireless_bridge", "gateway") or suspected_component_id in self.nodes:
            # Component is a device node
            node = self.nodes.get(suspected_component_id)
            if not node:
                return []
            if node.type == "access_point":
                target_aps = [node.id]
            else:
                target_aps = self.get_downstream_access_points(node.id)

        # Collect subscribers served by the affected access points
        affected = [
            AffectedSubscriber(
                id=sub.id,
                display_name=sub.display_name,
                access_point_id=sub.access_point_id,
            )
            for sub in self.subscribers.values()
            if sub.access_point_id in target_aps
        ]
        # Sort deterministically by subscriber id
        affected.sort(key=lambda s: s.id)
        return affected
