"""
Provider registry.

Reads TOPOLOGY_PROVIDER and DEPENDENCY_ADAPTER from settings and returns
the appropriate provider/adapter instance.

Member 1 can plug in their Neo4j implementations into backend/app/engine/ –
the API routers require zero changes.
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

    Supported values for TOPOLOGY_PROVIDER:
      simulated  – SimulatedTopologyProvider (default, no Neo4j required)
      neo4j      – Member 1's Neo4jTopologyProvider (import added when ready)
    """
    name = settings.topology_provider.lower()

    if name == "simulated":
        return SimulatedTopologyProvider()

    if name == "neo4j":
        try:
            from app.engine.neo4j_provider import Neo4jTopologyProvider  # type: ignore[import]
            return Neo4jTopologyProvider(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "TOPOLOGY_PROVIDER=neo4j but app.engine.neo4j_provider is not "
                "implemented yet. Set TOPOLOGY_PROVIDER=simulated or ask "
                "Member 1 to provide Neo4jTopologyProvider."
            ) from exc

    raise ValueError(
        f"Unknown TOPOLOGY_PROVIDER={name!r}. "
        "Valid values: 'simulated', 'neo4j'."
    )


def get_dependency_adapter() -> DependencyAnalysisAdapter:
    """
    Factory used as a FastAPI dependency for affected-subscriber analysis.

    Supported values for DEPENDENCY_ADAPTER:
      unavailable – UnavailableDependencyAdapter (default honest behavior, returns 503)
      simulated   – SimulatedDependencyAdapter (demo mapping from simulated topology)
      neo4j       – Member 1's Neo4j dependency engine
    """
    name = settings.dependency_adapter.lower()

    if name == "unavailable":
        return UnavailableDependencyAdapter()

    if name == "simulated":
        return SimulatedDependencyAdapter()

    if name == "neo4j":
        try:
            from app.engine.neo4j_dependency import Neo4jDependencyAdapter  # type: ignore[import]
            return Neo4jDependencyAdapter(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
            )
        except ModuleNotFoundError as exc:
            raise GraphEngineUnavailableError(
                "DEPENDENCY_ADAPTER=neo4j but app.engine.neo4j_dependency is not "
                "implemented yet. Ask Member 1 to provide Neo4jDependencyAdapter."
            ) from exc

    raise ValueError(
        f"Unknown DEPENDENCY_ADAPTER={name!r}. "
        "Valid values: 'unavailable', 'simulated', 'neo4j'."
    )
