"""Integration tests for live Neo4j / Neo4j Aura database.

Marked with @pytest.mark.integration.

Execution Rules:
1. If NEO4J_URI or credentials are not configured, tests are skipped with a clear explanation.
2. If credentials are configured but connection or authentication fails, the test FAILS
   explicitly with a clear, sanitized failure report (never prints passwords).
3. Uses isolated test data (prefix 'TEST_') so live runs never overwrite or mutate the
   village demo topology.
"""

from typing import List
import pytest
from backend.app.engine import (
    Neo4jClient,
    Neo4jGraphStore,
    Subscriber,
    TopologyLink,
    TopologyNode,
)


def get_isolated_test_nodes() -> List[TopologyNode]:
    """Returns isolated test nodes prefixed with TEST_."""
    return [
        TopologyNode(
            id="TEST_GW1",
            type="gateway",
            label="Test Gateway PoP",
            status="healthy",
        ),
        TopologyNode(
            id="TEST_R1",
            type="router",
            label="Test Core Router",
            status="healthy",
        ),
        TopologyNode(
            id="TEST_WB1",
            type="wireless_bridge",
            label="Test Wireless Bridge Tx",
            status="healthy",
        ),
        TopologyNode(
            id="TEST_WB2",
            type="wireless_bridge",
            label="Test Wireless Bridge Rx",
            status="healthy",
        ),
        TopologyNode(
            id="TEST_AP1",
            type="access_point",
            label="Test North Village AP",
            status="healthy",
        ),
        TopologyNode(
            id="TEST_AP2",
            type="access_point",
            label="Test South Village AP",
            status="healthy",
        ),
    ]


def get_isolated_test_links() -> List[TopologyLink]:
    """Returns isolated test links prefixed with TEST_."""
    return [
        TopologyLink(
            id="TEST_L1",
            source="TEST_GW1",
            target="TEST_R1",
            status="healthy",
            latency_ms=15.0,
            packet_loss_pct=0.0,
            throughput_mbps=100.0,
        ),
        TopologyLink(
            id="TEST_L2",
            source="TEST_R1",
            target="TEST_WB1",
            status="healthy",
            latency_ms=2.0,
            packet_loss_pct=0.0,
            throughput_mbps=80.0,
        ),
        TopologyLink(
            id="TEST_L3",
            source="TEST_WB1",
            target="TEST_WB2",
            status="healthy",
            latency_ms=25.0,
            packet_loss_pct=0.5,
            throughput_mbps=35.0,
        ),
        TopologyLink(
            id="TEST_L4",
            source="TEST_WB2",
            target="TEST_AP1",
            status="healthy",
            latency_ms=3.0,
            packet_loss_pct=0.0,
            throughput_mbps=50.0,
        ),
        TopologyLink(
            id="TEST_L5",
            source="TEST_R1",
            target="TEST_AP2",
            status="healthy",
            latency_ms=5.0,
            packet_loss_pct=0.0,
            throughput_mbps=60.0,
        ),
    ]


def get_isolated_test_subscribers() -> List[Subscriber]:
    """Returns isolated test subscribers prefixed with TEST_."""
    return [
        Subscriber(
            id="TEST_SUB101",
            display_name="Test Subscriber 101",
            access_point_id="TEST_AP1",
            plan="Basic",
        ),
        Subscriber(
            id="TEST_SUB102",
            display_name="Test Subscriber 102",
            access_point_id="TEST_AP1",
            plan="Enterprise",
        ),
        Subscriber(
            id="TEST_SUB201",
            display_name="Test Subscriber 201",
            access_point_id="TEST_AP2",
            plan="Community",
        ),
        Subscriber(
            id="TEST_SUB202",
            display_name="Test Subscriber 202",
            access_point_id="TEST_AP2",
            plan="Community",
        ),
        Subscriber(
            id="TEST_SUB203",
            display_name="Test Subscriber 203",
            access_point_id="TEST_AP2",
            plan="Basic",
        ),
    ]


@pytest.fixture(scope="module")
def live_neo4j_store():
    """Provides a live Neo4jGraphStore or handles skips/failures appropriately."""
    client = Neo4jClient()

    # 1. Skip cleanly if credentials/URI are not configured
    is_missing, missing_reason = client.has_missing_credentials()
    if is_missing:
        pytest.skip(f"Neo4j integration tests skipped: {missing_reason}")

    # 2. If credentials ARE configured, verify connectivity; fail loudly if connection fails
    health = client.check_connection()
    if not health.get("connected", False):
        pytest.fail(
            f"Failed to connect to configured Neo4j instance at {client.sanitized_uri}: "
            f"{health.get('error')}"
        )

    store = Neo4jGraphStore(client=client)

    # Clean up any leftover test data before running
    store.delete_isolated_test_data(prefix="TEST_")

    yield store

    # Clean up isolated test data after running
    try:
        store.delete_isolated_test_data(prefix="TEST_")
    finally:
        client.close()


@pytest.mark.integration
def test_neo4j_live_idempotent_seeding(live_neo4j_store: Neo4jGraphStore):
    """Validates live idempotent seeding in Neo4j using isolated test data."""
    test_nodes = get_isolated_test_nodes()
    test_links = get_isolated_test_links()
    test_subs = get_isolated_test_subscribers()

    # 1. First seed
    res1 = live_neo4j_store.seed_topology(
        nodes=test_nodes,
        links=test_links,
        subscribers=test_subs,
    )
    assert res1["status"] == "seeded"
    assert res1["nodes_count"] == len(test_nodes)
    assert res1["links_count"] == len(test_links)
    assert res1["subscribers_count"] == len(test_subs)

    # 2. Second seed (idempotent: no duplicates)
    res2 = live_neo4j_store.seed_topology(
        nodes=test_nodes,
        links=test_links,
        subscribers=test_subs,
    )
    assert res2["status"] == "seeded"
    assert res2["nodes_count"] == len(test_nodes)

    # 3. Verify counts of isolated test elements in Neo4j
    topo = live_neo4j_store.get_topology(prefix="TEST_")
    assert len(topo.nodes) == len(test_nodes)
    assert len(topo.links) == len(test_links)
    assert {n.id for n in topo.nodes} == {n.id for n in test_nodes}
    assert {l.id for l in topo.links} == {l.id for l in test_links}


@pytest.mark.integration
def test_neo4j_live_subscriber_dependencies(live_neo4j_store: Neo4jGraphStore):
    """Validates downstream subscriber dependency traversal in live Neo4j using isolated test data."""
    test_nodes = get_isolated_test_nodes()
    test_links = get_isolated_test_links()
    test_subs = get_isolated_test_subscribers()

    # Ensure test topology is present
    live_neo4j_store.seed_topology(
        nodes=test_nodes,
        links=test_links,
        subscribers=test_subs,
    )

    # 1. Query downstream from TEST_L3 (wireless bridge hop) -> reaches TEST_AP1 only
    aff_l3 = live_neo4j_store.get_affected_subscribers(
        suspected_component_id="TEST_L3",
        component_type="link",
    )
    assert aff_l3.count == 2
    assert {s.id for s in aff_l3.subscribers} == {"TEST_SUB101", "TEST_SUB102"}

    # 2. Query downstream from TEST_L1 (core gateway backhaul) -> reaches all TEST APs
    aff_l1 = live_neo4j_store.get_affected_subscribers(
        suspected_component_id="TEST_L1",
        component_type="link",
    )
    assert aff_l1.count == 5
    assert {s.id for s in aff_l1.subscribers} == {
        "TEST_SUB101",
        "TEST_SUB102",
        "TEST_SUB201",
        "TEST_SUB202",
        "TEST_SUB203",
    }

    # 3. Query downstream from TEST_L5 (south distribution link) -> reaches TEST_AP2 only
    aff_l5 = live_neo4j_store.get_affected_subscribers(
        suspected_component_id="TEST_L5",
        component_type="link",
    )
    assert aff_l5.count == 3
    assert {s.id for s in aff_l5.subscribers} == {
        "TEST_SUB201",
        "TEST_SUB202",
        "TEST_SUB203",
    }
