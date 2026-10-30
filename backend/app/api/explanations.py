"""
Incident explanation endpoint.

Implements:
- POST /api/v1/incidents/{incident_id}/explain

Follows docs/api-contract.md Section 10.
"""
from __future__ import annotations

import sqlite3
from fastapi import APIRouter, Depends, HTTPException, status

from app.db.connection import get_db
from app.db.repository import get_incident
from app.providers.explanations import (
    ExplanationProvider,
    ExplanationProviderUnavailableError,
)
from app.providers.registry import get_explanation_provider
from app.schemas.explanation import (
    IncidentExplanationRequest,
    IncidentExplanationResponse,
)

router = APIRouter(tags=["explanations"])


@router.post(
    "/incidents/{incident_id}/explain",
    response_model=IncidentExplanationResponse,
    status_code=status.HTTP_200_OK,
    summary="Explain incident in natural language",
    description=(
        "Generates an explainable root-cause summary for an incident in the requested language (e.g. Hindi). "
        "Explanations must be grounded in verified diagnostic incident data."
    ),
)
def explain_incident(
    incident_id: str,
    payload: IncidentExplanationRequest,
    db: sqlite3.Connection = Depends(get_db),
    provider: ExplanationProvider = Depends(get_explanation_provider),
) -> IncidentExplanationResponse:
    """
    Validate incident existence, generate natural language explanation via configured provider, and return result.

    - 200: Incident successfully explained.
    - 404: Incident not found in database.
    - 422: Invalid request payload (e.g. empty or blank language).
    - 503: Configured explanation provider is unavailable or offline.
    """
    # 1. Verify target incident exists in operational storage
    incident = get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    # 2. Invoke explanation provider
    try:
        explanation_text = provider.explain_incident(incident, payload.language)
    except ExplanationProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return IncidentExplanationResponse(
        incident_id=incident_id,
        language=payload.language,
        explanation=explanation_text,
        provider=provider.provider_name,
    )
