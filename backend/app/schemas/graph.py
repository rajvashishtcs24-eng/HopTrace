"""
Pydantic schemas for graph status and intelligence endpoints — HopTrace Track N.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class GraphStatusResponse(BaseModel):
    backend: Literal["neo4j", "memory"] = Field(..., description="Active graph backend ('neo4j' or 'memory')")
    fallback: bool = Field(..., description="True if Neo4j failed/unavailable and fell back to in-memory")
    latency_ms: Optional[float] = Field(None, description="Connection latency in milliseconds")
    last_error: Optional[str] = Field(None, description="Sanitized generic error message (if any)")
    reason: Optional[str] = Field(None, description="Reason for status/fallback mode")


class GraphSubscriberItem(BaseModel):
    id: str = Field(..., description="Unique subscriber ID (e.g. SUB101)")
    name: str = Field(..., description="Subscriber name / label")
    village: Optional[str] = Field(None, description="Associated village name")
    is_essential: bool = Field(False, description="Whether subscriber is an essential public service")


class GraphBlastRadius(BaseModel):
    count: int = Field(..., description="Total count of affected subscribers")
    subscribers: List[GraphSubscriberItem] = Field(
        default_factory=list,
        description="List of affected subscribers sorted by priority (essential first)",
    )


class GraphPath(BaseModel):
    nodes: List[str] = Field(default_factory=list, description="Node IDs in failure path from gateway")
    links: List[str] = Field(default_factory=list, description="Link IDs in failure path from gateway")


class GraphHistory(BaseModel):
    link_id: Optional[str] = Field(None, description="Failed link or component ID")
    incidents_30d: int = Field(0, description="Count of incidents on this component in the last 30 days")


class GraphQueryMetric(BaseModel):
    name: str = Field(..., description="Query name (e.g. blast_radius, path, history)")
    cypher: str = Field(..., description="Executed Cypher query string")
    rows: int = Field(..., description="Number of rows returned")
    ms: float = Field(..., description="Execution time in milliseconds")


class IncidentGraphResponse(BaseModel):
    backend: Literal["neo4j", "memory"] = Field(..., description="Active graph backend used for this incident query")
    fallback: bool = Field(False, description="Whether query fell back to in-memory store due to Neo4j unavailability")
    simulated: bool = Field(False, description="Whether this is a simulated / lab incident")
    blast_radius: GraphBlastRadius = Field(..., description="Downstream subscriber blast radius")
    path: GraphPath = Field(..., description="Network path from gateway to failed component")
    history: GraphHistory = Field(..., description="30-day incident frequency history")
    queries: List[GraphQueryMetric] = Field(
        default_factory=list,
        description="Executed graph queries and performance metrics",
    )
