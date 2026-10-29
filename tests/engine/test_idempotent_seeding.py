"""Automated tests for idempotent topology seeding."""

import pytest
from backend.app.engine import (
    InMemoryGraphStore,
    get_default_links,
    get_default_nodes,
    get_default_subscribers,
    seed_topology,
    get_topology,
)


def test_in_memory_idempotent_seeding():
    """Validates that repeated seeding on in-memory store does not duplicate elements."""
    store = InMemoryGraphStore()

    # First seed
    res1 = store.seed_topology()
    assert res1["nodes_count"] == len(get_default_nodes())
    assert res1["links_count"] == len(get_default_links())
    assert res1["subscribers_count"] == len(get_default_subscribers())

    # Second seed
    res2 = store.seed_topology()
    assert res2["nodes_count"] == res1["nodes_count"]
    assert res2["links_count"] == res1["links_count"]
    assert res2["subscribers_count"] == res1["subscribers_count"]

    # Third seed
    res3 = store.seed_topology()
    assert res3["nodes_count"] == res1["nodes_count"]
    assert res3["links_count"] == res1["links_count"]
    assert res3["subscribers_count"] == res1["subscribers_count"]

    topo = store.get_topology()
    assert len(topo.nodes) == len(get_default_nodes())
    assert len(topo.links) == len(get_default_links())


def test_facade_idempotent_seeding():
    """Validates repeated seeding through engine facade."""
    res1 = seed_topology(force_in_memory=True)
    res2 = seed_topology(force_in_memory=True)

    assert res1["nodes_count"] == res2["nodes_count"]
    assert res1["links_count"] == res2["links_count"]
    assert res1["subscribers_count"] == res2["subscribers_count"]

    topo = get_topology(force_in_memory=True)
    node_ids = [n.id for n in topo.nodes]
    link_ids = [l.id for l in topo.links]

    # No duplicate IDs exist
    assert len(node_ids) == len(set(node_ids))
    assert len(link_ids) == len(set(link_ids))
