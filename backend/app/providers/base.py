"""
Topology provider interface.

Member 1 implements Neo4jTopologyProvider in backend/app/engine/ (their
namespace).  This abstract base class defines the contract so the API layer
stays decoupled from any specific graph backend.

Adding a new provider:
1. Subclass TopologyProvider.
2. Implement `get_topology()`.
3. Register it in `backend/app/providers/registry.py`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.topology import TopologyResponse


class TopologyProvider(ABC):
    """Return the current network topology."""

    @abstractmethod
    def get_topology(self) -> TopologyResponse:
        """
        Fetch topology data and return a TopologyResponse.

        Raises:
            TopologyUnavailableError: when the underlying source cannot be
                reached (e.g. Neo4j is offline).
        """
        ...


class TopologyUnavailableError(RuntimeError):
    """Raised when the topology provider cannot reach its data source."""
