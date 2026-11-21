"""
Graph backend status and intelligence endpoints — HopTrace Track N.

Implements:
- GET /api/v1/graph/status
- GET /api/v1/incidents/{incident_id}/graph
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.db.connection import get_db
from app.db.repository import (
    get_incident,
    get_incident_history_30d,
    get_subscribers_by_ids,
)
from app.engine.facade import get_engine, get_graph_status
from app.engine.graph_store import Neo4jGraphStore
from app.engine.neo4j_client import sanitize_last_error
from app.engine.topology import classify_essential
from app.schemas.graph import (
    GraphBlastRadius,
    GraphHistory,
    GraphPath,
    GraphQueryMetric,
    GraphStatusResponse,
    GraphSubscriberItem,
    IncidentGraphResponse,
)

router = APIRouter(tags=["graph"])
logger = logging.getLogger(__name__)

AP_TO_VILLAGE: Dict[str, str] = {
    "AP1": "rampur",
    "AP2": "rampur",
    "AP3": "bhatpur",
    "AP4": "bhatpur",
    "AP5": "daulatpur",
    "AP6": "daulatpur",
}


def _enrich_subscribers(
    db: sqlite3.Connection,
    records: List[Dict[str, Any]],
    engine: Optional[Any] = None,
) -> List[GraphSubscriberItem]:
    """Enriches graph blast-radius subscriber records with SQLite details (no phone numbers).

    Sorts essential public services to the top of the list for restore prioritization.
    """
    sub_ids = [r["id"] for r in records if "id" in r]
    full_subs_map: Dict[str, Dict[str, Any]] = {}
    if sub_ids:
        for s in get_subscribers_by_ids(db, sub_ids):
            full_subs_map[s["id"]] = s

    enriched: List[GraphSubscriberItem] = []
    for r in records:
        sid = r["id"]
        sqlite_sub = full_subs_map.get(sid, {})
        name = sqlite_sub.get("display_name") or r.get("name") or r.get("display_name") or sid
        ap_id = sqlite_sub.get("access_point_id") or r.get("access_point_id", "")

        village = AP_TO_VILLAGE.get(ap_id)
        if not village and engine and hasattr(engine, "in_memory_store"):
            village = engine.in_memory_store.graph.get_village_for_ap(ap_id)
        if not village:
            village = "Unknown"

        is_essential = classify_essential(name)

        enriched.append(
            GraphSubscriberItem(
                id=sid,
                name=name,
                village=village.lower(),
                is_essential=is_essential,
            )
        )

    # Priority sort: essential services first, then alphabetical by ID
    enriched.sort(key=lambda s: (not s.is_essential, s.id))
    return enriched


def _build_memory_incident_response(
    engine: Any,
    db: sqlite3.Connection,
    component_id: str,
    component_type: str,
    is_simulated: bool,
    fallback: bool,
) -> IncidentGraphResponse:
    """Builds graph incident analysis using in-memory store and SQLite incident history."""
    mem_records, _ = engine.in_memory_store.get_affected_subscribers_with_query(
        suspected_component_id=component_id,
        component_type=component_type,
    )
    subscribers = _enrich_subscribers(db, mem_records, engine=engine)

    path_dict, _ = engine.in_memory_store.get_failure_path(
        component_id=component_id,
        component_type=component_type,
        gateway_id="GW1",
    )

    # Fallback history reads from SQLite incidents table, never from memory store.
    # Simulated incidents return 0 (only data_source = 'live' incidents count towards history).
    hist_count = 0 if is_simulated else get_incident_history_30d(db, component_id, days=30)

    return IncidentGraphResponse(
        backend="memory",
        fallback=fallback,
        simulated=is_simulated,
        blast_radius=GraphBlastRadius(count=len(subscribers), subscribers=subscribers),
        path=GraphPath(
            nodes=path_dict.get("nodes", []),
            links=path_dict.get("links", []),
        ),
        history=GraphHistory(link_id=component_id, incidents_30d=hist_count),
        queries=[],
    )


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


@router.get(
    "/incidents/{incident_id}/graph",
    response_model=IncidentGraphResponse,
    summary="Get graph analysis for an incident (blast radius, path, history)",
    description=(
        "Returns downstream subscriber blast radius, network failure path from gateway, "
        "and 30-day incident history with real Cypher queries and timings. "
        "Operates via Neo4j when healthy, falling back safely to in-memory and SQLite."
    ),
)
def get_incident_graph(
    incident_id: str,
    db: sqlite3.Connection = Depends(get_db),
) -> IncidentGraphResponse:
    """Provides Neo4j graph-powered incident intelligence with in-memory & SQLite fallback."""
    # 1. Look up incident in SQLite or engine memory
    engine = get_engine()
    incident = get_incident(db, incident_id)
    if incident is None:
        try:
            mem_inc = engine.get_incident(incident_id)
            if mem_inc is not None:
                incident = mem_inc.model_dump() if hasattr(mem_inc, "model_dump") else mem_inc.dict()
        except Exception:
            pass

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    # 2. Extract suspected component details
    component_id = incident.get("suspected_component_id") or "L1"
    raw_type = incident.get("suspected_component_type")
    if raw_type:
        component_type = "link" if raw_type.lower() == "link" else "node"
    else:
        component_type = "link" if component_id.startswith("L") else "node"

    data_source = (incident.get("data_source") or "simulated").lower()
    is_live = (data_source == "live")
    is_simulated = not is_live

    # 3. Lab / simulated incidents never touch Neo4j (labeled simulated with backend 'memory')
    from app.config import settings
    configured_backend = settings.graph_backend.lower()

    if is_simulated or configured_backend == "memory":
        return _build_memory_incident_response(
            engine=engine,
            db=db,
            component_id=component_id,
            component_type=component_type,
            is_simulated=is_simulated,
            fallback=False,
        )

    # 4. Live incident with auto/neo4j backend: query Neo4j
    store = engine.get_active_store()
    if isinstance(store, Neo4jGraphStore):
        try:
            queries: List[GraphQueryMetric] = []

            # 4a. Blast radius query (handles both failed links and failed nodes)
            records, br_query = store.get_affected_subscribers_with_query(
                suspected_component_id=component_id,
                component_type=component_type,
            )
            queries.append(GraphQueryMetric(**br_query))

            # 4b. Failure path query (shortestPath using LINK*..10)
            path_dict, path_query = store.get_failure_path(
                component_id=component_id,
                component_type=component_type,
                gateway_id="GW1",
            )
            queries.append(GraphQueryMetric(**path_query))

            # 4c. Non-blocking idempotent incident write (MERGE on id) - never in ingest path
            sub_ids = [r["id"] for r in records if "id" in r]
            store.record_incident_node(
                incident_id=incident["id"],
                component_id=component_id,
                component_type=component_type,
                cause=incident.get("summary") or "Network degradation",
                started_at=incident.get("created_at"),
                resolved_at=incident.get("resolved_at"),
                subscriber_ids=sub_ids,
            )

            # 4d. History query (30-day chronic links)
            hist_count, hist_query = store.get_incident_history(
                component_id=component_id,
                days=30,
            )
            queries.append(GraphQueryMetric(**hist_query))

            # 4e. Enrich subscribers with SQLite details (village, is_essential; NO phone numbers)
            subscribers = _enrich_subscribers(db, records, engine=engine)

            return IncidentGraphResponse(
                backend="neo4j",
                fallback=False,
                simulated=False,
                blast_radius=GraphBlastRadius(count=len(subscribers), subscribers=subscribers),
                path=GraphPath(
                    nodes=path_dict.get("nodes", []),
                    links=path_dict.get("links", []),
                ),
                history=GraphHistory(link_id=component_id, incidents_30d=hist_count),
                queries=queries,
            )
        except Exception as exc:
            clean_err = sanitize_last_error(exc)
            logger.warning("Neo4j incident graph query failed, falling back to memory: %s", clean_err)
            engine._neo4j_fallback = True
            engine._neo4j_last_error = clean_err

    # 5. Fallback path (Neo4j unreachable or threw error)
    return _build_memory_incident_response(
        engine=engine,
        db=db,
        component_id=component_id,
        component_type=component_type,
        is_simulated=False,
        fallback=True,
    )
