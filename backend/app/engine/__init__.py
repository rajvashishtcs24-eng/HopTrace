"""HopTrace Network Intelligence Engine.

Exports core models, diagnostic engine, simulated telemetry, graph stores,
and facade methods for backend integration.
"""

from backend.app.engine.models import (
    AffectedSubscriber,
    AffectedSubscribersResponse,
    ComponentType,
    EvidenceItem,
    IncidentDetails,
    LinkStatus,
    Measurement,
    NetworkTopology,
    NodeStatus,
    NodeType,
    RunMeasurementsResponse,
    ScenarioRunResponse,
    Subscriber,
    TopologyLink,
    TopologyNode,
)
from backend.app.engine.neo4j_client import Neo4jClient, get_neo4j_client
from backend.app.engine.topology import (
    InMemoryTopologyGraph,
    get_default_links,
    get_default_nodes,
    get_default_subscribers,
    get_default_topology,
)
from backend.app.engine.telemetry import (
    BASELINE_TELEMETRY,
    SEVERITY_FACTORS,
    SimulatedTelemetryGenerator,
)
from backend.app.engine.diagnostics import (
    DiagnosticEngine,
    diagnose,
)
from backend.app.engine.graph_store import (
    InMemoryGraphStore,
    Neo4jGraphStore,
)
from backend.app.engine.facade import (
    HopTraceEngine,
    check_neo4j_health,
    get_affected_subscribers,
    get_engine,
    get_incident_details,
    get_latest_incident,
    get_run_measurements,
    get_topology,
    run_scenario,
    seed_topology,
)

__all__ = [
    # Models
    "AffectedSubscriber",
    "AffectedSubscribersResponse",
    "ComponentType",
    "EvidenceItem",
    "IncidentDetails",
    "LinkStatus",
    "Measurement",
    "NetworkTopology",
    "NodeStatus",
    "NodeType",
    "RunMeasurementsResponse",
    "ScenarioRunResponse",
    "Subscriber",
    "TopologyLink",
    "TopologyNode",
    # Neo4j Client
    "Neo4jClient",
    "get_neo4j_client",
    # Topology
    "InMemoryTopologyGraph",
    "get_default_links",
    "get_default_nodes",
    "get_default_subscribers",
    "get_default_topology",
    # Telemetry
    "BASELINE_TELEMETRY",
    "SEVERITY_FACTORS",
    "SimulatedTelemetryGenerator",
    # Diagnostics
    "DiagnosticEngine",
    "diagnose",
    # Stores
    "InMemoryGraphStore",
    "Neo4jGraphStore",
    # Facade
    "HopTraceEngine",
    "get_engine",
    "check_neo4j_health",
    "get_affected_subscribers",
    "get_incident_details",
    "get_latest_incident",
    "get_run_measurements",
    "get_topology",
    "run_scenario",
    "seed_topology",
]
