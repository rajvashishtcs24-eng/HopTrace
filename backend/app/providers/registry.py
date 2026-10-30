"""
Provider registry.

Selects topology providers and dependency adapters from application settings.
"""
from __future__ import annotations

from app.config import settings
from app.providers.base import TopologyProvider
from app.providers.dependencies import (
    DependencyAnalysisAdapter,
    GraphEngineUnavailableError,
    SimulatedDependencyAdapter,
    UnavailableDependencyAdapter,
)
from app.providers.simulated import SimulatedTopologyProvider


def get_topology_provider() -> TopologyProvider:
    """
    Factory used as a FastAPI dependency for network topology.

    Supported TOPOLOGY_PROVIDER values:
      simulated - Standalone simulated topology
      engine    - HopTrace graph engine (Neo4j with in-memory fallback)
    """
    name = settings.topology_provider.lower()

    if name == "simulated":
        return SimulatedTopologyProvider()

    if name == "engine":
        from app.providers.engine_topology import EngineTopologyProvider

        return EngineTopologyProvider()

    raise ValueError(
        f"Unknown TOPOLOGY_PROVIDER={name!r}. "
        "Valid values: 'simulated', 'engine'."
    )


def get_dependency_adapter() -> DependencyAnalysisAdapter:
    """
    Factory used as a FastAPI dependency for affected-subscriber analysis.

    Supported DEPENDENCY_ADAPTER values:
      unavailable - Explicitly unavailable adapter (returns 503)
      simulated   - Standalone demo mapping
      engine      - HopTrace graph engine (when implemented)
    """
    name = settings.dependency_adapter.lower()

    if name == "unavailable":
        return UnavailableDependencyAdapter()

    if name == "simulated":
        return SimulatedDependencyAdapter()

    if name == "engine":
        return UnavailableDependencyAdapter(
            "The engine dependency adapter is unavailable: dependency analysis "
            "integration has not been implemented yet."
        )

    raise ValueError(
        f"Unknown DEPENDENCY_ADAPTER={name!r}. "
        "Valid values: 'unavailable', 'simulated', 'engine'."
    )
