"""
Pydantic schemas for incident retrieval and affected-subscriber endpoints.

Follows docs/api-contract.md Sections 4, 5, and 6.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

DataSource = Literal["simulated", "measured"]


class IncidentResponse(BaseModel):
    id: str = Field(..., description="Unique incident identifier (e.g. incident-001)")
    run_id: Optional[str] = Field(None, description="Associated test run ID if triggered by lab test")
    status: str = Field(..., description="Incident status (e.g. open, resolved)")
    suspected_component_id: Optional[str] = Field(None, description="Suspected faulty component ID (e.g. L2)")
    suspected_component_type: Optional[str] = Field(None, description="Type of suspected component (e.g. link, node)")
    summary: str = Field(..., description="Human-readable incident summary")
    confidence_score: Optional[float] = Field(
        None,
        description="Confidence score in range [0.0, 1.0]. Null until a validated scoring method is implemented.",
    )
    evidence: list[Any] = Field(
        default_factory=list,
        description="Observed metrics, baselines, and thresholds supporting the diagnosis.",
    )
    uncertainty_note: Optional[str] = Field(
        None,
        description="Explanation of diagnostic uncertainty or ambiguity.",
    )
    data_source: DataSource = Field(
        ...,
        description="'simulated' or 'measured'. Must never mislabel simulated data as measured.",
    )
    created_at: str = Field(
        ...,
        description="Creation timestamp in ISO 8601 UTC format (e.g. 2026-10-29T10:00:00Z).",
    )


class AffectedSubscriberItem(BaseModel):
    id: str = Field(..., description="Subscriber identifier (e.g. SUB101)")
    display_name: str = Field(..., description="Subscriber display name")
    access_point_id: str = Field(..., description="Access point subscriber connects through")


class AffectedSubscribersResponse(BaseModel):
    count: int = Field(..., description="Total count of affected subscribers. Must match len(subscribers).")
    subscribers: list[AffectedSubscriberItem] = Field(
        ...,
        description="List of subscriber records determined by network dependencies.",
    )
