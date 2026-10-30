# HopTrace Graph Model & Network Intelligence Engine

**Project:** HopTrace  
**Hackathon:** hackFront India — T3.2, Running a Village Internet Business  
**Module:** Network Intelligence Engine (`backend/app/engine`)  
**Specification:** Aligned with [`docs/api-contract.md`](file:///c:/Users/rajva/Documents/HopTrace/docs/api-contract.md)

---

## 1. Graph Model & Schema

HopTrace uses Neo4j to model the physical and logical backhaul infrastructure of a rural village internet service provider. Network components and subscriber dependencies are represented as native graph nodes and relationships.

### 1.1 Node Labels and Properties

#### `Device` Nodes
Every physical network equipment item carries the primary label `:Device` and a secondary type label:

1. **`:Gateway:Device`**
   - **Role:** Point of Presence (PoP) upstream fiber backhaul termination.
   - **Properties:**
     - `id: STRING` (e.g., `"GW1"`, unique key)
     - `label: STRING` (e.g., `"Upstream Gateway (Fiber PoP)"`)
     - `type: STRING` (`"gateway"`)
     - `status: STRING` (`"healthy"`, `"degraded"`, `"down"`)

2. **`:Router:Device`**
   - **Role:** Core village distribution router (e.g. mounted on a panchayat tower).
   - **Properties:** `id`, `label`, `type` (`"router"`), `status`

3. **`:WirelessBridge:Device`**
   - **Role:** Point-to-Point (PtP) wireless transmission bridge (e.g. 5GHz/60GHz link across village terrain).
   - **Properties:** `id`, `label`, `type` (`"wireless_bridge"`), `status`

4. **`:AccessPoint:Device`**
   - **Role:** Wireless access point serving local village wards, markets, and panchayats.
   - **Properties:** `id`, `label`, `type` (`"access_point"`), `status`

#### `Subscriber` Nodes
Represents village businesses, institutions, and community members receiving internet service:
- **Label:** `:Subscriber`
- **Properties:**
  - `id: STRING` (e.g., `"SUB101"`, unique key)
  - `display_name: STRING` (e.g., `"Ramesh Patel (Kishan Kirana)"`)
  - `access_point_id: STRING` (e.g., `"AP1"`)
  - `plan: STRING` (`"Basic"`, `"Enterprise"`, `"Community"`)
  - `status: STRING` (`"active"`, `"suspended"`)
  - `payment_status: STRING` (`"paid"`, `"due"`)
  - `due_date: STRING` (ISO 8601 date, e.g., `"2026-11-01"`)

---

### 1.2 Relationship Types

#### 1. `[:LINK]`
Connects two devices from upstream source to downstream target:
```cypher
(source:Device)-[:LINK {
  id: "L3",
  status: "healthy",
  latency_ms: 25.0,
  packet_loss_pct: 0.5,
  throughput_mbps: 35.0
}]->(target:Device)
```
- **Properties:**
  - `id: STRING` (stable link identifier, e.g., `"L1"`, `"L2"`)
  - `status: STRING` (`"healthy"`, `"degraded"`, `"down"`)
  - `latency_ms: FLOAT`
  - `packet_loss_pct: FLOAT`
  - `throughput_mbps: FLOAT`

#### 2. `[:SERVES]`
Connects an access point to a subscriber:
```cypher
(ap:AccessPoint:Device)-[:SERVES]->(sub:Subscriber)
```

---

### 1.3 Graph Constraints

Unique identity constraints ensure idempotent operations:

```cypher
CREATE CONSTRAINT device_id_unique IF NOT EXISTS
FOR (d:Device) REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT subscriber_id_unique IF NOT EXISTS
FOR (s:Subscriber) REQUIRE s.id IS UNIQUE;
```

---

## 2. Initial Topology

The initial testbed models a rural village internet setup:

```
[GW1: Upstream Gateway]
         |
         | L1 (Fiber Backhaul)
         v
  [R1: Village Core Router]
     |                 |
     | L2              | L5 (Ethernet Distribution)
     v                 v
[WB1: Bridge Tx]   [AP2: South Village AP]
     |                 |
     | L3 (PtP Hop)    +---> SUB201 (Primary Health Centre)
     v                 +---> SUB202 (Govt Secondary School)
[WB2: Bridge Rx]       +---> SUB203 (Manoj CSC Center)
     |
     | L4 (Ethernet)
     v
[AP1: North Village AP]
     |
     +---> SUB101 (Ramesh Patel - Kishan Kirana)
     +---> SUB102 (Gram Panchayat e-Seva Kendra)
```

### Topology Routing Assumption
**Single-path routing:** Subscribers do not have alternate redundant paths unless explicitly represented in the graph. Therefore, failure or severe degradation on an intermediate backhaul link (e.g., `L3`) severs or degrades backhaul for all access points and subscribers located topologically downstream from the link target.

---

## 3. Parameterized Cypher Queries

### 3.1 Idempotent Seeding Query
Running this query multiple times does not duplicate nodes or relationships:

```cypher
// 1. Upsert Devices
UNWIND $devices AS dev
MERGE (d:Device {id: dev.id})
SET d.label = dev.label,
    d.type = dev.type,
    d.status = dev.status
FOREACH (_ IN CASE WHEN dev.type = 'gateway' THEN [1] ELSE [] END | SET d:Gateway)
FOREACH (_ IN CASE WHEN dev.type = 'router' THEN [1] ELSE [] END | SET d:Router)
FOREACH (_ IN CASE WHEN dev.type = 'wireless_bridge' THEN [1] ELSE [] END | SET d:WirelessBridge)
FOREACH (_ IN CASE WHEN dev.type = 'access_point' THEN [1] ELSE [] END | SET d:AccessPoint);

// 2. Upsert Subscribers
UNWIND $subscribers AS sub
MERGE (s:Subscriber {id: sub.id})
SET s.display_name = sub.display_name,
    s.access_point_id = sub.access_point_id,
    s.plan = sub.plan,
    s.status = sub.status,
    s.payment_status = sub.payment_status,
    s.due_date = sub.due_date;

// 3. Upsert Links
UNWIND $links AS lk
MATCH (src:Device {id: lk.source})
MATCH (tgt:Device {id: lk.target})
MERGE (src)-[r:LINK {id: lk.id}]->(tgt)
SET r.status = lk.status,
    r.latency_ms = lk.latency_ms,
    r.packet_loss_pct = lk.packet_loss_pct,
    r.throughput_mbps = lk.throughput_mbps;

// 4. Upsert AccessPoint -> Subscriber relationships
UNWIND $subscribers AS sub
MATCH (ap:Device {id: sub.access_point_id})
MATCH (s:Subscriber {id: sub.id})
MERGE (ap)-[r:SERVES]->(s);
```

### 3.2 Retrieve Topology Query
```cypher
MATCH (d:Device)
RETURN d.id AS id, d.type AS type, d.label AS label, d.status AS status
ORDER BY d.id;

MATCH (src:Device)-[r:LINK]->(tgt:Device)
RETURN r.id AS id, src.id AS source, tgt.id AS target, r.status AS status,
       r.latency_ms AS latency_ms, r.packet_loss_pct AS packet_loss_pct,
       r.throughput_mbps AS throughput_mbps
ORDER BY r.id;
```

### 3.3 Affected Subscribers Dependency Query
Finds all subscribers whose connection depends on a suspected link:

```cypher
MATCH (src:Device)-[rel:LINK {id: $component_id}]->(tgt:Device)
MATCH (tgt)-[:LINK*0..]->(ap:Device)-[:SERVES]->(sub:Subscriber)
WHERE ap.type = 'access_point'
RETURN DISTINCT sub.id AS id, sub.display_name AS display_name, ap.id AS access_point_id
ORDER BY sub.id;
```

When querying a suspected node (e.g. an access point or core router):
```cypher
MATCH (n:Device {id: $component_id})-[:LINK*0..]->(ap:Device)-[:SERVES]->(sub:Subscriber)
WHERE ap.type = 'access_point'
RETURN DISTINCT sub.id AS id, sub.display_name AS display_name, ap.id AS access_point_id
ORDER BY sub.id;
```

---

## 4. Simulated Telemetry Model

All telemetry produced by the engine is explicitly marked with `"data_source": "simulated"`. Measurements are deterministic and generated using a documented mathematical baseline model. **No LLM is used to generate measurements, and they are not claimed to be from a live ISP.**

### 4.1 Documented Baselines
- **`L1` (Fiber Backhaul):** Latency = 15.0 ms, Packet Loss = 0.0%, Throughput = 100.0 Mbps, Connectivity = OK
- **`L2` (Tower Ethernet):** Latency = 2.0 ms, Packet Loss = 0.0%, Throughput = 80.0 Mbps, Connectivity = OK
- **`L3` (PtP Wireless Bridge):** Latency = 25.0 ms, Packet Loss = 0.5%, Throughput = 35.0 Mbps, Connectivity = OK
- **`L4` (North AP Ethernet):** Latency = 3.0 ms, Packet Loss = 0.0%, Throughput = 50.0 Mbps, Connectivity = OK
- **`L5` (South AP Ethernet):** Latency = 5.0 ms, Packet Loss = 0.0%, Throughput = 60.0 Mbps, Connectivity = OK

### 4.2 Controlled Degradation Scaling
When a scenario injects a fault into a link, the metrics scale predictably:
- **Low severity:** Latency +35 ms, Packet Loss +5.0%, Throughput $\times 0.70$ (-30%)
- **Medium severity:** Latency +90 ms, Packet Loss +15.0%, Throughput $\times 0.40$ (-60%)
- **High severity:** Latency +175 ms, Packet Loss +25.0%, Throughput $\times 0.15$ (-85%)

---

## 5. Explainable Fault Localization Engine

### 5.1 CRITICAL VALIDATION RULE
The diagnostic function **does not receive** the injected fault ID, scenario name, or ground truth label as input. It inspects **solely** the observed measurements, documented baselines, and graph topology. The test harness compares the prediction with the ground truth only in the evaluation assertion layer.

### 5.2 Metric Anomaly Normalization
For each link $l$:
1. **Connectivity Failure ($s_{\text{conn}}$):**
   $$s_{\text{conn}} = \begin{cases} 1.0 & \text{if } \text{connectivity\_ok is False} \\ 0.0 & \text{otherwise} \end{cases}$$
2. **Packet Loss Abnormality ($s_{\text{loss}}$):**
   $$\Delta_{\text{loss}} = \max(0, \text{loss}_{\text{obs}} - \text{loss}_{\text{base}})$$
   $$s_{\text{loss}} = \begin{cases} 0.0 & \text{if } \Delta_{\text{loss}} \le 1.0\% \\ \min(1.0, \frac{\Delta_{\text{loss}}}{25.0}) & \text{otherwise} \end{cases}$$
3. **Latency Inflation ($s_{\text{lat}}$):**
   $$\Delta_{\text{lat}} = \max(0, \text{latency}_{\text{obs}} - \text{latency}_{\text{base}})$$
   $$s_{\text{lat}} = \begin{cases} 0.0 & \text{if } \Delta_{\text{lat}} \le 10.0\text{ ms} \\ \min(1.0, \frac{\Delta_{\text{lat}}}{150.0}) & \text{otherwise} \end{cases}$$
4. **Throughput Degradation ($s_{\text{tp}}$):**
   $$\Delta_{\text{drop}} = \max(0, \frac{\text{tp}_{\text{base}} - \text{tp}_{\text{obs}}}{\text{tp}_{\text{base}}})$$
   $$s_{\text{tp}} = \begin{cases} 0.0 & \text{if } \Delta_{\text{drop}} \le 0.15 \\ \min(1.0, \frac{\Delta_{\text{drop}} - 0.15}{0.70}) & \text{otherwise} \end{cases}$$

### 5.3 Composite Diagnostic Score
The overall anomaly score $S \in [0.0, 1.0]$ combines the normalized metrics with explainable weights:
$$S = (0.40 \cdot s_{\text{conn}}) + (0.30 \cdot s_{\text{loss}}) + (0.20 \cdot s_{\text{lat}}) + (0.10 \cdot s_{\text{tp}})$$

- **Detection Threshold:** $S \ge 0.10$ marks a degraded component.
- **Normal Baseline:** $S < 0.10$ indicates normal operation (incident not opened).

### 5.4 Ambiguity & Missing Telemetry Rules
- **Ambiguous Evidence:** If the top two suspect links both score $\ge 0.10$ and $|S_1 - S_2| \le 0.08$, the engine reports ambiguity:
  - `uncertainty_note`: `"Ambiguous evidence: Link 'L2' (score 0.42) and Link 'L3' (score 0.42) show comparable degradation..."`
  - `confidence_score`: Proportional to score difference, avoiding false claims of certainty.
- **Missing Telemetry:** If measurements are null or omitted, the link is **never assumed healthy**. It is marked unmonitored and an uncertainty warning is attached to the incident.

---

## 6. Python Engine Interfaces for Backend Integration

The backend developer can import stable, typed functions directly from `backend.app.engine`:

```python
from backend.app.engine import (
    seed_topology,
    get_topology,
    run_scenario,
    get_latest_incident,
    get_incident_details,
    get_affected_subscribers,
    get_run_measurements,
    check_neo4j_health,
)
```

### Interface Signatures

#### 1. `seed_topology(force_in_memory: bool = False) -> Dict[str, Any]`
Idempotently seeds nodes, links, and subscribers.
- **Returns:** `{"status": "seeded", "nodes_count": 6, "links_count": 5, "subscribers_count": 5}`

#### 2. `get_topology(force_in_memory: bool = False) -> NetworkTopology`
Returns topology matching `GET /api/v1/topology`.
- **Returns:** Pydantic `NetworkTopology` (`nodes`, `links`, `data_source="simulated"`).

#### 3. `run_scenario(scenario: str, target_link_id: Optional[str] = None, severity: str = "medium", ...) -> ScenarioRunResponse`
Executes simulated testbed, triggers fault localization, and registers run & incident.
- **Returns:** `ScenarioRunResponse(run_id="run-001", data_source="simulated", measurements_count=5, incident_id="incident-001")`

#### 4. `get_incident_details(incident_id: str) -> Optional[IncidentDetails]`
Retrieves incident matching `GET /api/v1/incidents/{incident_id}`.
- **Returns:** Pydantic `IncidentDetails` containing `suspected_component_id`, `evidence`, `uncertainty_note`, `confidence_score`.

#### 5. `get_latest_incident() -> Optional[IncidentDetails]`
Retrieves the most recent incident or `None` if no incident has been opened.

#### 6. `get_affected_subscribers(incident_id: str, force_in_memory: bool = False) -> AffectedSubscribersResponse`
Traces downstream subscribers matching `GET /api/v1/incidents/{incident_id}/affected-subscribers`.
- **Returns:** `AffectedSubscribersResponse(count=2, subscribers=[...])`

#### 7. `get_run_measurements(run_id: str) -> Optional[RunMeasurementsResponse]`
Retrieves telemetry measurements matching `GET /api/v1/runs/{run_id}/measurements`.

#### 8. `check_neo4j_health() -> Dict[str, Any]`
Verifies Neo4j connectivity.
- **Returns:** `{"connected": True/False, "uri": "...", "error": ...}`

---

## 7. Setup & Execution Commands

### Environment Variables & Neo4j Aura Configuration
Configure Neo4j credentials in `.env` (or OS environment):
```bash
# For Neo4j Aura (Cloud):
NEO4J_URI=neo4j+s://<dbid>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_aura_password_here

# Or for local development:
# NEO4J_URI=neo4j://localhost:7687
# NEO4J_USERNAME=neo4j
# NEO4J_PASSWORD=your_password
```

### Security & Isolation
- **Credentials Protection:** Passwords and tokens are never printed or included in error logs. URIs are automatically sanitized.
- **Integration Test Isolation:** Live integration tests use isolated `TEST_` prefixed nodes and links. They never overwrite or mutate the village demo topology (`GW1`, `R1`, `SUB101`, etc.) and automatically clean up after execution.
- **Diagnostic Behavior:**
  - If credentials are not configured, integration tests skip cleanly with a specific explanation.
  - If credentials are configured but connectivity or authentication fails, tests report the actual error clearly.

### Running Tests
1. **Run pure unit tests (zero external dependencies required):**
   ```bash
   python -m pytest tests/engine -m "not integration" -v
   ```
2. **Run complete test suite (includes live Neo4j Aura integration tests):**
   ```bash
   python -m pytest tests/engine -v
   ```
