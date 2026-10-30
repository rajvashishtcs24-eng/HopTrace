"""
Incident retrieval and affected-subscriber endpoints.

Implements:
- GET /api/v1/incidents/latest
- GET /api/v1/incidents/{incident_id}
- GET /api/v1/incidents/{incident_id}/affected-subscribers

Follows docs/api-contract.md Sections 4, 5, and 6.
"""
from __future__ import annotations

import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.db.connection import get_db
from app.db.repository import get_incident, get_latest_incident
from app.providers.dependencies import (
    DependencyAnalysisAdapter,
    GraphEngineUnavailableError,
)
from app.providers.registry import get_dependency_adapter
from app.schemas.incident import (
    AffectedSubscriberItem,
    AffectedSubscribersResponse,
    IncidentResponse,
)

router = APIRouter(tags=["incidents"])


@router.get(
    "/incidents/latest",
    response_model=Optional[IncidentResponse],
    summary="Get latest diagnostic incident",
    description=(
        "Returns the most recent diagnostic incident, or null if no incident has been created."
    ),
)
def get_latest(
    db: sqlite3.Connection = Depends(get_db),
) -> Optional[IncidentResponse]:
    """Retrieve the most recent incident or return null."""
    incident = get_latest_incident(db)
    if incident is None:
        return None
    return IncidentResponse(**incident)


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    summary="Get incident details",
    description="Returns detailed diagnostic information for a specific incident.",
)
def get_by_id(
    incident_id: str,
    db: sqlite3.Connection = Depends(get_db),
) -> IncidentResponse:
    """Retrieve an incident by ID or return 404 Not Found."""
    incident = get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )
    return IncidentResponse(**incident)


@router.get(
    "/incidents/{incident_id}/affected-subscribers",
    response_model=AffectedSubscribersResponse,
    summary="Get affected subscribers for an incident",
    description=(
        "Determines affected subscribers using network dependencies. "
        "Returns 503 if Member 1's graph dependency engine is not integrated or available."
    ),
)
def get_affected_subscribers(
    incident_id: str,
    db: sqlite3.Connection = Depends(get_db),
    adapter: DependencyAnalysisAdapter = Depends(get_dependency_adapter),
) -> AffectedSubscribersResponse:
    """
    Determine affected subscribers based on graph dependencies.

    - 200: Affected subscribers successfully determined.
    - 404: Incident ID not found.
    - 503: Graph dependency engine is unavailable.
    """
    # 1. Verify incident exists
    incident = get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    # 2. Invoke dependency analysis adapter
    try:
        subscribers = adapter.get_affected_subscribers(
            incident_id=incident_id,
            suspected_component_id=incident.get("suspected_component_id"),
            suspected_component_type=incident.get("suspected_component_type"),
            db_conn=db,
        )
    except GraphEngineUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return AffectedSubscribersResponse(
        count=len(subscribers),
        subscribers=[AffectedSubscriberItem(**s) for s in subscribers],
    )
