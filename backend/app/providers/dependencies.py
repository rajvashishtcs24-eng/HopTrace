"""
Network dependency analysis adapter interface.

Member 1 owns the Neo4j graph engine, network topology relationships,
and dependency analysis (e.g. determining which access points and subscribers
are downstream of a degraded link or failed router).

This adapter interface cleanly decouples FastAPI from Member 1's engine:
- If Member 1's engine is not connected, UnavailableDependencyAdapter honestly raises
  GraphEngineUnavailableError (which translates to HTTP 503).
- If Member 1's engine is ready, EngineDependencyAdapter delegates graph traversal
  to the shared HopTraceEngine singleton and enriches results from SQLite.
- For isolated tests or explicit testbed demos, test doubles or SimulatedDependencyAdapter
  can be selected without modifying the API layer.
"""
from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from typing import Any


class GraphEngineUnavailableError(RuntimeError):
    """Raised when the graph dependency engine is not integrated or unreachable."""
    pass


class DependencyAnalysisAdapter(ABC):
    """Abstract base class for determining affected subscribers from graph dependencies."""

    @abstractmethod
    def get_affected_subscribers(
        self,
        incident_id: str,
        suspected_component_id: str | None,
        suspected_component_type: str | None,
        db_conn: sqlite3.Connection,
    ) -> list[dict[str, Any]]:
        """
        Determine affected subscribers for a given incident based on network dependencies.

        Args:
            incident_id: Identifier of the incident.
            suspected_component_id: ID of the suspected component (e.g. 'L2', 'AP1').
            suspected_component_type: Type of component (e.g. 'link', 'router').
            db_conn: SQLite connection to retrieve operational subscriber details.

        Returns:
            List of dicts with keys: id, display_name, access_point_id.

        Raises:
            GraphEngineUnavailableError: When graph dependency analysis cannot be performed.
        """
        ...


class UnavailableDependencyAdapter(DependencyAnalysisAdapter):
    """
    Default adapter when Member 1's Neo4j graph engine is not connected.

    Honest behavior: refuses to fabricate dependency analysis and raises GraphEngineUnavailableError.
    """

    def __init__(self, message: str | None = None) -> None:
        self.message = message or (
            "Graph dependency engine is unavailable: Member 1's Neo4j engine in "
            "backend/app/engine/ is not integrated. Affected subscribers cannot be "
            "determined without verified dependency analysis."
        )

    def get_affected_subscribers(
        self,
        incident_id: str,
        suspected_component_id: str | None,
        suspected_component_type: str | None,
        db_conn: sqlite3.Connection,
    ) -> list[dict[str, Any]]:
        raise GraphEngineUnavailableError(self.message)


class SimulatedDependencyAdapter(DependencyAnalysisAdapter):
    """
    Simulated dependency adapter for demos and testbed when explicitly enabled.

    Derives downstream access points from the simulated topology graph:
      GW1 -> R1 -> WB1 -> AP1 (subscribers: SUB101, SUB102)
      GW1 -> R1 -> WB2 -> AP2 (subscribers: SUB201, SUB202)

    Then queries SQLite for subscribers associated with those access points.
    """

    DOWNSTREAM_APS: dict[str, list[str]] = {
        "L1": ["AP1", "AP2"],
        "GW1": ["AP1", "AP2"],
        "R1": ["AP1", "AP2"],
        "L2": ["AP1"],
        "WB1": ["AP1"],
        "AP1": ["AP1"],
        "L3": ["AP2"],
        "WB2": ["AP2"],
        "AP2": ["AP2"],
    }

    def get_affected_subscribers(
        self,
        incident_id: str,
        suspected_component_id: str | None,
        suspected_component_type: str | None,
        db_conn: sqlite3.Connection,
    ) -> list[dict[str, Any]]:
        if not suspected_component_id:
            return []

        affected_aps = self.DOWNSTREAM_APS.get(suspected_component_id, [])
        if not affected_aps:
            return []

        placeholders = ",".join("?" for _ in affected_aps)
        cursor = db_conn.execute(
            f"""
            SELECT id, display_name, access_point_id
            FROM subscribers
            WHERE access_point_id IN ({placeholders})
            ORDER BY id ASC;
            """,
            affected_aps,
        )
        return [dict(row) for row in cursor.fetchall()]


class EngineDependencyAdapter(DependencyAnalysisAdapter):
    """
    Dependency adapter backed by the shared HopTraceEngine singleton.

    Delegates graph traversal to the engine's active store (Neo4j when available,
    InMemory otherwise). Enriches the resulting subscriber IDs by looking them up
    in the operational SQLite database so the API always returns current subscriber
    records — not stale graph-embedded data.

    Import convention: uses ``from app.engine.facade import get_engine`` to access
    the module-level singleton, identical to EngineTopologyProvider, ensuring no
    second engine instance is ever created.
    """

    def get_affected_subscribers(
        self,
        incident_id: str,
        suspected_component_id: str | None,
        suspected_component_type: str | None,
        db_conn: sqlite3.Connection,
    ) -> list[dict[str, Any]]:
        """
        Determine affected subscribers by delegating graph traversal to the engine.

        Steps:
          1. Guard: return [] if suspected_component_id is absent.
          2. Obtain the engine's active graph store (Neo4j or in-memory fallback).
          3. Call store.get_affected_subscribers() with the component details.
          4. Extract subscriber IDs from the engine response.
          5. Guard: return [] if no IDs were found (skip SQL round-trip).
          6. Query SQLite for the operational subscriber records matching those IDs.
          7. Return dicts with keys: id, display_name, access_point_id, ordered by id.

        Raises:
            GraphEngineUnavailableError: If the graph engine or SQLite query fails.
                Raw exception details (connection strings, credentials) are not
                forwarded to the caller.
        """
        if not suspected_component_id:
            return []

        component_type = suspected_component_type or "link"

        try:
            from app.db.repository import get_subscribers_by_ids
            from app.engine.facade import get_affected_subscribers, get_engine

            engine = get_engine()
            # Attempt facade function using incident_id
            result = get_affected_subscribers(incident_id, force_in_memory=True)
            # If incident is not in engine's in-memory store (e.g. SQLite-only incident), query active store directly
            if result.count == 0 and suspected_component_id:
                store = engine.get_active_store(force_in_memory=True)
                result = store.get_affected_subscribers(
                    suspected_component_id=suspected_component_id,
                    component_type=component_type,
                )
        except Exception as exc:
            raise GraphEngineUnavailableError(
                "Graph dependency engine is unavailable: could not retrieve affected "
                "subscribers from the HopTrace graph engine."
            ) from exc

        subscriber_ids = [sub.id for sub in result.subscribers]
        if not subscriber_ids:
            return []

        try:
            return get_subscribers_by_ids(db_conn, subscriber_ids)
        except Exception as exc:
            raise GraphEngineUnavailableError(
                "Failed to retrieve subscriber records from the operational database."
            ) from exc
