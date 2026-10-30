"""
Tests for GET /api/v1/topology.

Verifies:
  - HTTP 200 status code.
  - Response contains required top-level keys: nodes, links, data_source.
  - data_source is one of the two allowed values: "simulated" or "measured".
  - Each node has: id, type, label, status.
  - node.type is one of the four documented node types.
  - Each link has: id, source, target, status.
  - Measurement fields (latency_ms, packet_loss_pct, throughput_mbps) are
    either float or null – never any other type.
  - Provider-unavailable behaviour: a provider that raises
    TopologyUnavailableError must produce HTTP 503.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.providers.base import TopologyProvider, TopologyUnavailableError
from app.providers.dependencies import (
    EngineDependencyAdapter,
    SimulatedDependencyAdapter,
    UnavailableDependencyAdapter,
)
from app.providers.engine_topology import EngineTopologyProvider
from app.providers.registry import get_dependency_adapter, get_topology_provider
from app.providers.simulated import SimulatedTopologyProvider

# ── helpers ──────────────────────────────────────────────────────────────────

VALID_NODE_TYPES    = {"gateway", "router", "wireless_bridge", "access_point"}
VALID_DATA_SOURCES  = {"simulated", "measured"}
VALID_STATUSES      = {"healthy", "degraded", "failed", "unknown"}
MEASUREMENT_FIELDS  = ("latency_ms", "packet_loss_pct", "throughput_mbps")


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def topology_response(client: TestClient) -> dict[str, Any]:
    """Shared parsed response body for topology tests."""
    return client.get("/api/v1/topology").json()


# ── basic structure ───────────────────────────────────────────────────────────

def test_topology_status_code(client: TestClient) -> None:
    """Topology endpoint must return HTTP 200."""
    response = client.get("/api/v1/topology")
    assert response.status_code == 200


def test_topology_top_level_keys(topology_response: dict) -> None:
    """Response must contain exactly the three documented top-level keys."""
    assert "nodes"       in topology_response
    assert "links"       in topology_response
    assert "data_source" in topology_response


def test_topology_nodes_is_list(topology_response: dict) -> None:
    assert isinstance(topology_response["nodes"], list)


def test_topology_links_is_list(topology_response: dict) -> None:
    assert isinstance(topology_response["links"], list)


# ── data_source ───────────────────────────────────────────────────────────────

def test_topology_data_source_is_valid(topology_response: dict) -> None:
    """data_source must be 'simulated' or 'measured' – nothing else."""
    assert topology_response["data_source"] in VALID_DATA_SOURCES


def test_topology_data_source_is_simulated_by_default(topology_response: dict) -> None:
    """Without a live Neo4j, the default provider must label data as 'simulated'."""
    assert topology_response["data_source"] == "simulated"


# ── node shape ────────────────────────────────────────────────────────────────

def test_topology_node_required_fields(topology_response: dict) -> None:
    """Every node must have id, type, label, status."""
    for node in topology_response["nodes"]:
        assert "id"     in node, f"node missing 'id': {node}"
        assert "type"   in node, f"node missing 'type': {node}"
        assert "label"  in node, f"node missing 'label': {node}"
        assert "status" in node, f"node missing 'status': {node}"


def test_topology_node_types_are_valid(topology_response: dict) -> None:
    """node.type must be one of the four documented values."""
    for node in topology_response["nodes"]:
        assert node["type"] in VALID_NODE_TYPES, (
            f"Unexpected node type {node['type']!r} for node {node['id']!r}"
        )


def test_topology_node_ids_are_unique(topology_response: dict) -> None:
    ids = [n["id"] for n in topology_response["nodes"]]
    assert len(ids) == len(set(ids)), "Duplicate node ids found"


# ── link shape ────────────────────────────────────────────────────────────────

def test_topology_link_required_fields(topology_response: dict) -> None:
    """Every link must have id, source, target, status."""
    for link in topology_response["links"]:
        assert "id"     in link, f"link missing 'id': {link}"
        assert "source" in link, f"link missing 'source': {link}"
        assert "target" in link, f"link missing 'target': {link}"
        assert "status" in link, f"link missing 'status': {link}"


def test_topology_link_ids_are_unique(topology_response: dict) -> None:
    ids = [l["id"] for l in topology_response["links"]]
    assert len(ids) == len(set(ids)), "Duplicate link ids found"


# ── nullable measurement fields ───────────────────────────────────────────────

def test_topology_measurement_fields_are_float_or_null(topology_response: dict) -> None:
    """
    The contract says measurement values may be null when unavailable.
    They must therefore be float or null – never a string or other type.
    """
    for link in topology_response["links"]:
        for field in MEASUREMENT_FIELDS:
            value = link.get(field)           # .get() returns None if key absent
            assert value is None or isinstance(value, (int, float)), (
                f"Link {link['id']!r}: field {field!r} = {value!r} "
                f"is neither float nor null"
            )


def test_topology_at_least_one_null_measurement(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The simulated provider intentionally leaves throughput_mbps null on one
    link to demonstrate the nullable-field contract works end-to-end.
    """
    monkeypatch.setattr(settings, "topology_provider", "simulated")
    response = client.get("/api/v1/topology").json()
    null_found = any(
        link.get("throughput_mbps") is None
        for link in response["links"]
    )
    assert null_found, (
        "Expected at least one link with throughput_mbps=null in simulated data"
    )


# ── provider-unavailable behaviour ───────────────────────────────────────────

class _FailingProvider(TopologyProvider):
    """Test double: always raises TopologyUnavailableError."""

    def get_topology(self):  # type: ignore[override]
        raise TopologyUnavailableError("test: backend offline")


def test_topology_503_when_provider_unavailable() -> None:
    """
    When the topology provider raises TopologyUnavailableError the endpoint
    must return HTTP 503 (Service Unavailable).
    """
    # Override the dependency with our failing test double.
    app.dependency_overrides[get_topology_provider] = lambda: _FailingProvider()
    try:
        with TestClient(app) as tc:
            response = tc.get("/api/v1/topology")
        assert response.status_code == 503, (
            f"Expected 503 but got {response.status_code}"
        )
        # The error detail must describe the failure, not be empty.
        body = response.json()
        assert "detail" in body
    finally:
        # Always restore so other tests are not affected.
        app.dependency_overrides.pop(get_topology_provider, None)


# ── provider unit tests ───────────────────────────────────────────────────────

def test_simulated_topology_provider_direct() -> None:
    provider = SimulatedTopologyProvider()
    resp = provider.get_topology()
    assert isinstance(resp.nodes, list)
    assert len(resp.nodes) == 6
    assert isinstance(resp.links, list)
    assert len(resp.links) == 5
    assert resp.data_source == "simulated"


def test_engine_topology_provider_direct() -> None:
    provider = EngineTopologyProvider()
    resp = provider.get_topology()
    assert isinstance(resp.nodes, list)
    assert len(resp.nodes) >= 6
    assert isinstance(resp.links, list)
    assert len(resp.links) >= 5
    assert resp.data_source in ("simulated", "measured")
    assert all(n.status in ("healthy", "degraded", "failed", "unknown") for n in resp.nodes)
    assert all(l.status in ("healthy", "degraded", "failed", "unknown") for l in resp.links)


def test_engine_topology_provider_does_not_seed_on_retrieval() -> None:
    with patch("app.providers.engine_topology.get_topology") as mock_get_topo, \
         patch("app.engine.facade.seed_topology") as mock_seed:
        mock_topo = MagicMock()
        mock_topo.nodes = []
        mock_topo.links = []
        mock_topo.data_source = "simulated"
        mock_get_topo.return_value = mock_topo

        provider = EngineTopologyProvider()
        provider.get_topology()

        mock_get_topo.assert_called_once()
        mock_seed.assert_not_called()


def test_engine_topology_provider_maps_down_to_failed() -> None:
    mock_topo = MagicMock()
    mock_node = MagicMock(id="N1", type="router", label="Router 1", status="down")
    mock_link = MagicMock(
        id="L1",
        source="N1",
        target="N2",
        status="down",
        latency_ms=10.0,
        packet_loss_pct=5.0,
        throughput_mbps=None,
    )
    mock_topo.nodes = [mock_node]
    mock_topo.links = [mock_link]
    mock_topo.data_source = "simulated"

    with patch("app.providers.engine_topology.get_topology", return_value=mock_topo):
        provider = EngineTopologyProvider()
        resp = provider.get_topology()
        assert resp.nodes[0].status == "failed"
        assert resp.links[0].status == "failed"


def test_engine_topology_provider_error_handling() -> None:
    with patch(
        "app.providers.engine_topology.get_topology",
        side_effect=RuntimeError("Engine failure"),
    ):
        provider = EngineTopologyProvider()
        with pytest.raises(TopologyUnavailableError) as exc_info:
            provider.get_topology()
        assert "Failed to retrieve topology" in str(exc_info.value)


def test_engine_topology_provider_empty_topology_raises() -> None:
    with patch("app.providers.engine_topology.get_topology", return_value=None):
        provider = EngineTopologyProvider()
        with pytest.raises(TopologyUnavailableError) as exc_info:
            provider.get_topology()
        assert "empty topology" in str(exc_info.value).lower()


# ── registry selection tests ─────────────────────────────────────────────────

def test_registry_selects_simulated_provider(monkeypatch) -> None:
    monkeypatch.setattr(settings, "topology_provider", "simulated")
    provider = get_topology_provider()
    assert isinstance(provider, SimulatedTopologyProvider)


def test_registry_selects_engine_provider(monkeypatch) -> None:
    monkeypatch.setattr(settings, "topology_provider", "engine")
    provider = get_topology_provider()
    assert isinstance(provider, EngineTopologyProvider)


def test_registry_invalid_topology_provider_fails(monkeypatch) -> None:
    monkeypatch.setattr(settings, "topology_provider", "invalid_provider")
    with pytest.raises(ValueError) as exc_info:
        get_topology_provider()
    assert "Unknown TOPOLOGY_PROVIDER='invalid_provider'" in str(exc_info.value)
    assert "'simulated', 'engine'" in str(exc_info.value)


def test_registry_dependency_adapter_selection(monkeypatch) -> None:
    monkeypatch.setattr(settings, "dependency_adapter", "unavailable")
    assert isinstance(get_dependency_adapter(), UnavailableDependencyAdapter)

    monkeypatch.setattr(settings, "dependency_adapter", "simulated")
    assert isinstance(get_dependency_adapter(), SimulatedDependencyAdapter)

    monkeypatch.setattr(settings, "dependency_adapter", "engine")
    assert isinstance(get_dependency_adapter(), EngineDependencyAdapter)

    monkeypatch.setattr(settings, "dependency_adapter", "unknown_val")
    with pytest.raises(ValueError) as exc_info:
        get_dependency_adapter()
    assert "Unknown DEPENDENCY_ADAPTER='unknown_val'" in str(exc_info.value)


# ── API integration with engine provider ─────────────────────────────────────

def test_topology_api_with_engine_provider(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "topology_provider", "engine")
    response = client.get("/api/v1/topology")
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) >= 6
    assert len(data["links"]) >= 5
    assert data["data_source"] in ("simulated", "measured")
    assert all(n["status"] in ("healthy", "degraded", "failed", "unknown") for n in data["nodes"])
    assert all(l["status"] in ("healthy", "degraded", "failed", "unknown") for l in data["links"])


def test_topology_api_with_engine_provider_error(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "topology_provider", "engine")
    with patch(
        "app.providers.engine_topology.get_topology",
        side_effect=RuntimeError("Graph engine crashed"),
    ):
        response = client.get("/api/v1/topology")
        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()

