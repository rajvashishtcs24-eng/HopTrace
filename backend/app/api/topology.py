"""
GET /api/v1/topology

Returns the current network topology (nodes, links, data_source).

The actual data comes from a TopologyProvider injected via FastAPI's
dependency-injection system.  This router never accesses Neo4j or any graph
engine directly – it only speaks the TopologyProvider interface.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.providers.base import TopologyProvider, TopologyUnavailableError
from app.providers.registry import get_topology_provider
from app.schemas.topology import TopologyResponse

router = APIRouter()


@router.get(
    "/topology",
    response_model=TopologyResponse,
    summary="Network topology",
    description=(
        "Returns the current network topology as a graph of nodes and links. "
        "`data_source` is 'simulated' when no live measurement backend is connected, "
        "or 'measured' when real telemetry is available."
    ),
)
def topology(
    provider: TopologyProvider = Depends(get_topology_provider),
) -> TopologyResponse:
    """
    Fetch topology from the configured provider.

    - 200: topology returned successfully.
    - 503: the underlying data source (e.g. Neo4j) is unreachable.
    """
    try:
        return provider.get_topology()
    except TopologyUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Topology data source unavailable: {exc}",
        ) from exc
