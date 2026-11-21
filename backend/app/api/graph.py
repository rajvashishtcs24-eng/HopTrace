"""
Graph backend status and intelligence endpoints — HopTrace Track N.

Implements:
- GET /api/v1/graph/status
"""
from __future__ import annotations

import logging
from fastapi import APIRouter

from app.engine.facade import get_graph_status
from app.schemas.graph import GraphStatusResponse

router = APIRouter(tags=["graph"])
logger = logging.getLogger(__name__)


@router.get(
    "/graph/status",
    response_model=GraphStatusResponse,
    summary="Get graph backend status",
    description=(
        "Returns active graph backend ('neo4j' or 'memory'), fallback state, "
        "connectivity latency in ms, and sanitized error (if any)."
    ),
)
def get_status() -> GraphStatusResponse:
    """Returns the current graph database connectivity and backend status."""
    status_dict = get_graph_status()
    return GraphStatusResponse(**status_dict)
