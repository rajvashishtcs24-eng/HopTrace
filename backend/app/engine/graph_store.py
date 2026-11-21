"""Graph store implementations for HopTrace.

Includes:
1. Neo4jGraphStore: Parameterized Cypher queries managing graph persistence
   and downstream subscriber dependency queries in Neo4j (including Neo4j Aura).
2. InMemoryGraphStore: High-fidelity in-memory graph store for fast unit
   testing without live database dependencies.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from .models import (
    AffectedSubscriber,
    AffectedSubscribersResponse,
    NetworkTopology,
    TopologyLink,
    TopologyNode,
    Subscriber,
)
from .neo4j_client import Neo4jClient, get_neo4j_client, sanitize_last_error
from .topology import (
    InMemoryTopologyGraph,
    classify_essential,
    get_default_links,
    get_default_nodes,
    get_default_subscribers,
    get_default_topology,
)

logger = logging.getLogger(__name__)


class Neo4jGraphStore:
    """Manages topology and dependency queries in Neo4j using parameterized Cypher."""

    def __init__(self, client: Optional[Neo4jClient] = None) -> None:
        self.client = client or get_neo4j_client()

    def create_constraints(self) -> None:
        """Idempotently creates unique constraints and indexes for Device, Subscriber, and Incident nodes."""
        c1 = (
            "CREATE CONSTRAINT device_id_unique IF NOT EXISTS "
            "FOR (d:Device) REQUIRE d.id IS UNIQUE"
        )
        c2 = (
            "CREATE CONSTRAINT subscriber_id_unique IF NOT EXISTS "
            "FOR (s:Subscriber) REQUIRE s.id IS UNIQUE"
        )
        c3 = (
            "CREATE CONSTRAINT incident_id_unique IF NOT EXISTS "
            "FOR (i:Incident) REQUIRE i.id IS UNIQUE"
        )
        c4 = (
            "CREATE INDEX incident_link_id_index IF NOT EXISTS "
            "FOR (i:Incident) ON (i.link_id)"
        )
        for cypher in (c1, c2, c3, c4):
            try:
                self.client.execute_write(cypher)
            except Exception:
                # Fallback gracefully if permissions or older Cypher syntax differ
                pass

    def seed_topology(
        self,
        nodes: Optional[List[TopologyNode]] = None,
        links: Optional[List[TopologyLink]] = None,
        subscribers: Optional[List[Subscriber]] = None,
    ) -> Dict[str, Any]:
        """Idempotently seeds nodes, links, and subscribers into Neo4j.

        Running this operation multiple times will NOT duplicate nodes or relationships.
        """
        self.create_constraints()

        node_list = nodes if nodes is not None else get_default_nodes()
        link_list = links if links is not None else get_default_links()
        sub_list = subscribers if subscribers is not None else get_default_subscribers()

        # 1. Upsert Device Nodes
        device_params = [
            {
                "id": n.id,
                "label": n.label,
                "type": n.type,
                "status": n.status,
            }
            for n in node_list
        ]
        seed_devices_cypher = """
        UNWIND $devices AS dev
        MERGE (d:Device {id: dev.id})
        SET d.label = dev.label,
            d.type = dev.type,
            d.status = dev.status
        FOREACH (_ IN CASE WHEN dev.type = 'gateway' THEN [1] ELSE [] END | SET d:Gateway)
        FOREACH (_ IN CASE WHEN dev.type = 'router' THEN [1] ELSE [] END | SET d:Router)
        FOREACH (_ IN CASE WHEN dev.type = 'wireless_bridge' THEN [1] ELSE [] END | SET d:WirelessBridge)
        FOREACH (_ IN CASE WHEN dev.type = 'access_point' THEN [1] ELSE [] END | SET d:AccessPoint)
        RETURN count(d) AS seeded_devices
        """
        self.client.execute_write(seed_devices_cypher, {"devices": device_params})

        # 2. Upsert Subscribers
        sub_params = [
            {
                "id": s.id,
                "display_name": s.display_name,
                "access_point_id": s.access_point_id,
                "plan": s.plan,
                "status": s.status,
                "payment_status": s.payment_status,
                "due_date": s.due_date,
            }
            for s in sub_list
        ]
        seed_subs_cypher = """
        UNWIND $subscribers AS sub
        MERGE (s:Subscriber {id: sub.id})
        SET s.display_name = sub.display_name,
            s.access_point_id = sub.access_point_id,
            s.plan = sub.plan,
            s.status = sub.status,
            s.payment_status = sub.payment_status,
            s.due_date = sub.due_date
        RETURN count(s) AS seeded_subscribers
        """
        self.client.execute_write(seed_subs_cypher, {"subscribers": sub_params})

        # 3. Upsert Links between devices
        link_params = [
            {
                "id": l.id,
                "source": l.source,
                "target": l.target,
                "status": l.status,
                "latency_ms": l.latency_ms,
                "packet_loss_pct": l.packet_loss_pct,
                "throughput_mbps": l.throughput_mbps,
            }
            for l in link_list
        ]
        seed_links_cypher = """
        UNWIND $links AS lk
        MATCH (src:Device {id: lk.source})
        MATCH (tgt:Device {id: lk.target})
        MERGE (src)-[r:LINK {id: lk.id}]->(tgt)
        SET r.status = lk.status,
            r.latency_ms = lk.latency_ms,
            r.packet_loss_pct = lk.packet_loss_pct,
            r.throughput_mbps = lk.throughput_mbps
        RETURN count(r) AS seeded_links
        """
        self.client.execute_write(seed_links_cypher, {"links": link_params})

        # 4. Upsert SERVES relationships from AccessPoints to Subscribers
        seed_serves_cypher = """
        UNWIND $subscribers AS sub
        MATCH (ap:Device {id: sub.access_point_id})
        MATCH (s:Subscriber {id: sub.id})
        MERGE (ap)-[r:SERVES]->(s)
        RETURN count(r) AS seeded_serves
        """
        self.client.execute_write(seed_serves_cypher, {"subscribers": sub_params})

        return {
            "status": "seeded",
            "nodes_count": len(node_list),
            "links_count": len(link_list),
            "subscribers_count": len(sub_list),
        }

    def get_topology(self, prefix: Optional[str] = None) -> NetworkTopology:
        """Retrieves topology from Neo4j, optionally filtered by ID prefix for test isolation."""
        if prefix:
            nodes_cypher = """
            MATCH (d:Device)
            WHERE d.id STARTS WITH $prefix
            RETURN d.id AS id, d.type AS type, d.label AS label, d.status AS status
            ORDER BY d.id
            """
            links_cypher = """
            MATCH (src:Device)-[r:LINK]->(tgt:Device)
            WHERE r.id STARTS WITH $prefix
            RETURN r.id AS id, src.id AS source, tgt.id AS target, r.status AS status,
                   r.latency_ms AS latency_ms, r.packet_loss_pct AS packet_loss_pct,
                   r.throughput_mbps AS throughput_mbps
            ORDER BY r.id
            """
            node_records = self.client.execute_query(nodes_cypher, {"prefix": prefix})
            link_records = self.client.execute_query(links_cypher, {"prefix": prefix})
        else:
            nodes_cypher = """
            MATCH (d:Device)
            RETURN d.id AS id, d.type AS type, d.label AS label, d.status AS status
            ORDER BY d.id
            """
            links_cypher = """
            MATCH (src:Device)-[r:LINK]->(tgt:Device)
            RETURN r.id AS id, src.id AS source, tgt.id AS target, r.status AS status,
                   r.latency_ms AS latency_ms, r.packet_loss_pct AS packet_loss_pct,
                   r.throughput_mbps AS throughput_mbps
            ORDER BY r.id
            """
            node_records = self.client.execute_query(nodes_cypher)
            link_records = self.client.execute_query(links_cypher)

        nodes = [
            TopologyNode(
                id=rec["id"],
                type=rec.get("type", "router"),
                label=rec.get("label", rec["id"]),
                status=rec.get("status", "healthy"),
            )
            for rec in node_records
        ]
        links = [
            TopologyLink(
                id=rec["id"],
                source=rec["source"],
                target=rec["target"],
                status=rec.get("status", "healthy"),
                latency_ms=rec.get("latency_ms"),
                packet_loss_pct=rec.get("packet_loss_pct"),
                throughput_mbps=rec.get("throughput_mbps"),
            )
            for rec in link_records
        ]

        return NetworkTopology(nodes=nodes, links=links, data_source="simulated")

    def get_affected_subscribers(
        self,
        suspected_component_id: str,
        component_type: str = "link",
    ) -> AffectedSubscribersResponse:
        """Traces downstream subscriber dependencies from the suspected link or node.

        Assumption:
        Single-path routing: Subscribers do not have alternate redundant paths
        unless explicitly represented in the graph.
        """
        records, _ = self.get_affected_subscribers_with_query(
            suspected_component_id=suspected_component_id,
            component_type=component_type,
        )
        subs = [
            AffectedSubscriber(
                id=r["id"],
                display_name=r.get("display_name") or r.get("name", r["id"]),
                access_point_id=r.get("access_point_id", ""),
            )
            for r in records
        ]
        return AffectedSubscribersResponse(count=len(subs), subscribers=subs)

    def get_affected_subscribers_with_query(
        self,
        suspected_component_id: str,
        component_type: str = "link",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Traces downstream subscriber dependencies with query metadata and timings.

        Uses LINK*0..10 bounded traversal and no unused variables.
        """
        if component_type == "link" or suspected_component_id.startswith("L"):
            cypher = """
            MATCH (:Device)-[:LINK {id: $component_id}]->(tgt:Device)
            MATCH (tgt)-[:LINK*0..10]->(ap:Device {type: 'access_point'})-[:SERVES]->(sub:Subscriber)
            RETURN DISTINCT sub.id AS id, sub.display_name AS display_name, sub.display_name AS name, ap.id AS access_point_id
            ORDER BY sub.id
            """
        else:
            cypher = """
            MATCH (failed:Device {id: $component_id})-[:LINK*0..10]->(ap:Device {type: 'access_point'})-[:SERVES]->(sub:Subscriber)
            RETURN DISTINCT sub.id AS id, sub.display_name AS display_name, sub.display_name AS name, ap.id AS access_point_id
            ORDER BY sub.id
            """

        t0 = time.perf_counter()
        records = self.client.execute_query(cypher, {"component_id": suspected_component_id})
        ms = round((time.perf_counter() - t0) * 1000, 2)

        query_meta = {
            "name": "blast_radius",
            "cypher": " ".join(cypher.split()),
            "rows": len(records),
            "ms": ms,
        }
        return records, query_meta

    def get_failure_path(
        self,
        component_id: str,
        component_type: str = "link",
        gateway_id: str = "GW1",
    ) -> Tuple[Dict[str, List[str]], Dict[str, Any]]:
        """Computes shortest path from gateway to the failed component using LINK*..10."""
        if component_type == "link" or component_id.startswith("L"):
            cypher = """
            MATCH (a:Device)-[target_rel:LINK {id: $component_id}]->(b:Device)
            OPTIONAL MATCH p = shortestPath((gw:Device {id: $gw_id})-[:LINK*..10]->(a))
            RETURN (CASE WHEN p IS NULL THEN [a.id, b.id] ELSE [n IN nodes(p) | n.id] + [b.id] END) AS nodes,
                   (CASE WHEN p IS NULL THEN [target_rel.id] ELSE [r IN relationships(p) | r.id] + [target_rel.id] END) AS links
            """
            params = {"component_id": component_id, "gw_id": gateway_id}
        else:
            cypher = """
            MATCH (dst:Device {id: $component_id})
            OPTIONAL MATCH p = shortestPath((gw:Device {id: $gw_id})-[:LINK*..10]->(dst))
            RETURN (CASE WHEN p IS NULL THEN [dst.id] ELSE [n IN nodes(p) | n.id] END) AS nodes,
                   (CASE WHEN p IS NULL THEN [] ELSE [r IN relationships(p) | r.id] END) AS links
            """
            params = {"component_id": component_id, "gw_id": gateway_id}

        t0 = time.perf_counter()
        records = self.client.execute_query(cypher, params)
        ms = round((time.perf_counter() - t0) * 1000, 2)

        if records and records[0].get("nodes"):
            nodes = records[0]["nodes"]
            links = records[0].get("links", [])
        else:
            nodes = [gateway_id]
            links = []

        query_meta = {
            "name": "path",
            "cypher": " ".join(cypher.split()),
            "rows": len(records),
            "ms": ms,
        }
        return {"nodes": nodes, "links": links}, query_meta

    def get_incident_history(
        self,
        component_id: str,
        days: int = 30,
    ) -> Tuple[int, Dict[str, Any]]:
        """Queries count of incidents on the component in the last 30 days from Neo4j (live incidents only)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cypher = """
        MATCH (i:Incident)
        WHERE (i.link_id = $component_id OR i.component_id = $component_id)
          AND i.data_source = 'live'
          AND i.started_at >= $cutoff
        RETURN count(i) AS incidents_30d
        """
        t0 = time.perf_counter()
        records = self.client.execute_query(cypher, {"component_id": component_id, "cutoff": cutoff})
        ms = round((time.perf_counter() - t0) * 1000, 2)

        count = 0
        if records and "incidents_30d" in records[0]:
            count = int(records[0]["incidents_30d"])
        elif records:
            count = len(records)

        query_meta = {
            "name": "history",
            "cypher": " ".join(cypher.split()),
            "rows": len(records),
            "ms": ms,
        }
        return count, query_meta

    def record_incident_node(
        self,
        incident_id: str,
        component_id: str,
        component_type: str = "link",
        cause: Optional[str] = None,
        started_at: Optional[str] = None,
        resolved_at: Optional[str] = None,
        subscriber_ids: Optional[List[str]] = None,
    ) -> bool:
        """Idempotently records an Incident node and relationships in Neo4j (best effort, non-blocking).

        Writes once per incident (MERGE on id) and tags data_source = 'live'.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        start = started_at or now_iso
        link_id = component_id if (component_type == "link" or component_id.startswith("L")) else None

        cypher = """
        MERGE (i:Incident {id: $id})
        SET i.link_id = $link_id,
            i.component_id = $component_id,
            i.cause = $cause,
            i.data_source = 'live',
            i.started_at = $started_at,
            i.resolved_at = $resolved_at
        WITH i
        FOREACH (_ IN CASE WHEN $component_id IS NOT NULL THEN [1] ELSE [] END |
            MERGE (d:Device {id: $component_id})
            MERGE (i)-[:AT]->(d)
        )
        WITH i
        FOREACH (sub_id IN $subscriber_ids |
            MERGE (s:Subscriber {id: sub_id})
            MERGE (i)-[:AFFECTED]->(s)
        )
        """
        params = {
            "id": incident_id,
            "link_id": link_id,
            "component_id": component_id,
            "cause": cause or "Network degradation",
            "started_at": start,
            "resolved_at": resolved_at,
            "subscriber_ids": subscriber_ids or [],
        }
        try:
            self.client.execute_write(cypher, params)
            return True
        except Exception as exc:
            logger.warning("Failed to record incident node in Neo4j: %s", sanitize_last_error(exc))
            return False

    def delete_isolated_test_data(self, prefix: str = "TEST_") -> None:
        """Removes test nodes and relationships starting with prefix without touching demo topology."""
        if not prefix:
            raise ValueError("Prefix cannot be empty for safe test data cleanup.")

        delete_subs = "MATCH (s:Subscriber) WHERE s.id STARTS WITH $prefix DETACH DELETE s"
        delete_devices = "MATCH (d:Device) WHERE d.id STARTS WITH $prefix DETACH DELETE d"
        try:
            self.client.execute_write(delete_subs, {"prefix": prefix})
            self.client.execute_write(delete_devices, {"prefix": prefix})
        except Exception:
            pass


class InMemoryGraphStore:
    """In-memory graph store for pure unit testing without a live Neo4j database."""

    def __init__(self) -> None:
        self.graph = InMemoryTopologyGraph()
        self.seed_count: int = 0

    def seed_topology(
        self,
        nodes: Optional[List[TopologyNode]] = None,
        links: Optional[List[TopologyLink]] = None,
        subscribers: Optional[List[Subscriber]] = None,
    ) -> Dict[str, Any]:
        """Idempotently seeds nodes, links, and subscribers."""
        node_list = nodes if nodes is not None else get_default_nodes()
        link_list = links if links is not None else get_default_links()
        sub_list = subscribers if subscribers is not None else get_default_subscribers()

        for n in node_list:
            self.graph.nodes[n.id] = n
        for l in link_list:
            self.graph.links[l.id] = l
        for s in sub_list:
            self.graph.subscribers[s.id] = s

        self.seed_count += 1
        return {
            "status": "seeded",
            "nodes_count": len(self.graph.nodes),
            "links_count": len(self.graph.links),
            "subscribers_count": len(self.graph.subscribers),
        }

    def get_topology(self, prefix: Optional[str] = None) -> NetworkTopology:
        """Returns the current network topology, optionally filtered by prefix."""
        nodes = list(self.graph.nodes.values())
        links = list(self.graph.links.values())
        if prefix:
            nodes = [n for n in nodes if n.id.startswith(prefix)]
            links = [l for l in links if l.id.startswith(prefix)]

        return NetworkTopology(
            nodes=nodes,
            links=links,
            data_source="simulated",
        )

    def get_affected_subscribers(
        self,
        suspected_component_id: str,
        component_type: str = "link",
    ) -> AffectedSubscribersResponse:
        """Returns affected subscribers based on the graph topology."""
        subs = self.graph.get_affected_subscribers(
            suspected_component_id=suspected_component_id,
            component_type=component_type,
        )
        return AffectedSubscribersResponse(count=len(subs), subscribers=subs)

    def get_affected_subscribers_with_query(
        self,
        suspected_component_id: str,
        component_type: str = "link",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """In-memory blast radius returning records and simulated query metadata."""
        subs = self.graph.get_affected_subscribers(
            suspected_component_id=suspected_component_id,
            component_type=component_type,
        )
        records = [
            {
                "id": s.id,
                "name": s.display_name,
                "display_name": s.display_name,
                "access_point_id": s.access_point_id,
            }
            for s in subs
        ]
        return records, {
            "name": "blast_radius",
            "cypher": "MEMORY_FALLBACK (BFS downstream access points)",
            "rows": len(records),
            "ms": 0.0,
        }

    def get_failure_path(
        self,
        component_id: str,
        component_type: str = "link",
        gateway_id: str = "GW1",
    ) -> Tuple[Dict[str, List[str]], Dict[str, Any]]:
        """Returns failure path from gateway using in-memory BFS."""
        path_dict = self.graph.get_path_from_gateway(
            target_id=component_id,
            component_type=component_type,
            gateway_id=gateway_id,
        )
        return path_dict, {
            "name": "path",
            "cypher": "MEMORY_FALLBACK (BFS shortest path)",
            "rows": len(path_dict.get("nodes", [])),
            "ms": 0.0,
        }

    def delete_isolated_test_data(self, prefix: str = "TEST_") -> None:
        """Removes test nodes and subscribers starting with prefix."""
        if not prefix:
            raise ValueError("Prefix cannot be empty for safe test data cleanup.")
        self.graph.nodes = {k: v for k, v in self.graph.nodes.items() if not k.startswith(prefix)}
        self.graph.links = {k: v for k, v in self.graph.links.items() if not k.startswith(prefix)}
        self.graph.subscribers = {
            k: v for k, v in self.graph.subscribers.items() if not k.startswith(prefix)
        }
