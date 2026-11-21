"""
Track N2 Parity Test: InMemoryGraphStore vs Neo4jGraphStore.

Verifies that for identical network topologies and failure injections:
- Link failures produce the exact same downstream affected subscriber IDs.
- Node failures produce the exact same downstream affected subscriber IDs.

How to run once Neo4j / Aura credentials are ready:
----------------------------------------------------
Set the following environment variables (server-side / local shell):
  $env:NEO4J_URI="neo4j+s://xxxx.databases.neo4j.io"
  $env:NEO4J_USER="neo4j"
  $env:NEO4J_PASSWORD="your-strong-password"
  $env:GRAPH_BACKEND="neo4j"

Then run this test file specifically:
  pytest tests/engine/test_graph_n2_parity.py -v -m integration
"""
from __future__ import annotations

from typing import List
import pytest

from app.engine.graph_store import InMemoryGraphStore, Neo4jGraphStore
from app.engine.models import Subscriber, TopologyLink, TopologyNode
from app.engine.neo4j_client import Neo4jClient


def get_parity_test_nodes() -> List[TopologyNode]:
    """Isolated test nodes prefixed with TEST_."""
    return [
        TopologyNode(id="TEST_GW1", type="gateway", label="Test Gateway", status="healthy"),
        TopologyNode(id="TEST_R1", type="router", label="Test Router", status="healthy"),
        TopologyNode(id="TEST_WB1", type="wireless_bridge", label="Test Bridge Tx", status="healthy"),
        TopologyNode(id="TEST_WB2", type="wireless_bridge", label="Test Bridge Rx", status="healthy"),
        TopologyNode(id="TEST_AP1", type="access_point", label="Test AP 1", status="healthy"),
        TopologyNode(id="TEST_AP2", type="access_point", label="Test AP 2", status="healthy"),
    ]


def get_parity_test_links() -> List[TopologyLink]:
    """Isolated test links prefixed with TEST_."""
    return [
        TopologyLink(id="TEST_L1", source="TEST_GW1", target="TEST_R1", status="healthy"),
        TopologyLink(id="TEST_L2", source="TEST_R1", target="TEST_WB1", status="healthy"),
        TopologyLink(id="TEST_L3", source="TEST_WB1", target="TEST_WB2", status="healthy"),
        TopologyLink(id="TEST_L4", source="TEST_WB2", target="TEST_AP1", status="healthy"),
        TopologyLink(id="TEST_L5", source="TEST_R1", target="TEST_AP2", status="healthy"),
    ]


def get_parity_test_subscribers() -> List[Subscriber]:
    """Isolated test subscribers prefixed with TEST_."""
    return [
        Subscriber(id="TEST_SUB101", display_name="Test Sub 101 PHC Hospital", access_point_id="TEST_AP1"),
        Subscriber(id="TEST_SUB102", display_name="Test Sub 102 Market", access_point_id="TEST_AP1"),
        Subscriber(id="TEST_SUB201", display_name="Test Sub 201 Panchayat", access_point_id="TEST_AP2"),
    ]


@pytest.fixture(scope="module")
def live_neo4j_store():
    """Provides a live Neo4jGraphStore or skips cleanly if credentials are not configured."""
    client = Neo4jClient()
    is_missing, missing_reason = client.has_missing_credentials()
    if is_missing:
        pytest.skip(f"Live Neo4j parity test skipped: {missing_reason}")

    health = client.check_connection()
    if not health.get("connected", False):
        pytest.fail(
            f"Failed to connect to configured Neo4j instance at {client.sanitized_uri}: "
            f"{health.get('error')}"
        )

    store = Neo4jGraphStore(client=client)
    nodes = get_parity_test_nodes()
    links = get_parity_test_links()
    subs = get_parity_test_subscribers()

    # Seed isolated test topology
    store.seed_topology(nodes=nodes, links=links, subscribers=subs)
    try:
        yield store
    finally:
        store.delete_isolated_test_data(prefix="TEST_")


@pytest.fixture(scope="module")
def memory_store():
    """Provides an in-memory graph store seeded with the same test topology."""
    store = InMemoryGraphStore()
    store.seed_topology(
        nodes=get_parity_test_nodes(),
        links=get_parity_test_links(),
        subscribers=get_parity_test_subscribers(),
    )
    return store


@pytest.mark.integration
def test_link_failure_parity(live_neo4j_store: Neo4jGraphStore, memory_store: InMemoryGraphStore) -> None:
    """Verify link failure L3 produces identical affected subscribers in both stores."""
    mem_resp = memory_store.get_affected_subscribers(suspected_component_id="TEST_L3", component_type="link")
    neo_resp = live_neo4j_store.get_affected_subscribers(suspected_component_id="TEST_L3", component_type="link")

    mem_ids = sorted([s.id for s in mem_resp.subscribers])
    neo_ids = sorted([s.id for s in neo_resp.subscribers])

    assert mem_ids == ["TEST_SUB101", "TEST_SUB102"]
    assert neo_ids == mem_ids
    assert neo_resp.count == mem_resp.count


@pytest.mark.integration
def test_node_failure_parity(live_neo4j_store: Neo4jGraphStore, memory_store: InMemoryGraphStore) -> None:
    """Verify node failure AP1 produces identical affected subscribers in both stores."""
    mem_resp = memory_store.get_affected_subscribers(suspected_component_id="TEST_AP1", component_type="node")
    neo_resp = live_neo4j_store.get_affected_subscribers(suspected_component_id="TEST_AP1", component_type="node")

    mem_ids = sorted([s.id for s in mem_resp.subscribers])
    neo_ids = sorted([s.id for s in neo_resp.subscribers])

    assert mem_ids == ["TEST_SUB101", "TEST_SUB102"]
    assert neo_ids == mem_ids
    assert neo_resp.count == mem_resp.count
