# HopTrace API Contract

Base path: /api/v1
Backend: Python + FastAPI

## 1. Health

GET /api/v1/health

Response:
{
  "status": "ok",
  "version": "0.1.0"
}

## 2. Network topology

GET /api/v1/topology

Response:
{
  "nodes": [
    {
      "id": "GW1",
      "type": "gateway",
      "label": "Upstream Gateway",
      "status": "healthy"
    }
  ],
  "links": [
    {
      "id": "L1",
      "source": "GW1",
      "target": "HOP1",
      "status": "healthy",
      "latency_ms": 20.0,
      "packet_loss_pct": 0.0,
      "throughput_mbps": 40.0
    }
  ],
  "data_source": "simulated"
}

Node types:
gateway, router, wireless_bridge, access_point

Link and measurement values may be null when unavailable.

data_source must be "simulated" or "measured".

## 3. Run a network test scenario

POST /api/v1/lab/run

Request:
{
  "scenario": "degrade_link",
  "target_link_id": "L2",
  "severity": "high"
}

Supported scenarios:
baseline, degrade_link, access_point_failure,
upstream_failure, ambiguous_fault

severity:
low, medium, high

target_link_id is required for degrade_link.
target_node_id is required for component failure scenarios.

Response:
{
  "run_id": "run-001",
  "data_source": "simulated",
  "measurements_count": 20,
  "incident_id": "incident-001"
}

The injected fault must remain separate from the
diagnostic engine's prediction. The diagnostic engine
must infer the likely fault from the observations.
Expected fault information must not be passed to the
diagnostic algorithm.

## 4. Latest incident

GET /api/v1/incidents/latest

Returns the most recent diagnostic incident, or null
if no incident has been created.

## 5. Incident details

GET /api/v1/incidents/{incident_id}

Response:
{
  "id": "incident-001",
  "run_id": "run-001",
  "status": "open",
  "suspected_component_id": "L2",
  "suspected_component_type": "link",
  "summary": "Potential intermediate-link degradation",
  "confidence_score": null,
  "evidence": [],
  "uncertainty_note": null,
  "data_source": "simulated",
  "created_at": "2026-10-29T10:00:00Z"
}

confidence_score may be null until a documented
scoring method is implemented. Do not invent confidence
values or claim validated accuracy without testing.

Evidence should include observed metrics and relevant
baselines or thresholds when available.

## 6. Affected subscribers

GET /api/v1/incidents/{incident_id}/affected-subscribers

Response:
{
  "count": 2,
  "subscribers": [
    {
      "id": "SUB101",
      "display_name": "Demo Subscriber 101",
      "access_point_id": "AP1"
    }
  ]
}

The count must match the returned subscriber records.
Determine affected subscribers using network dependencies.

## 7. Run measurements

GET /api/v1/runs/{run_id}/measurements

Response:
{
  "run_id": "run-001",
  "data_source": "simulated",
  "measurements": [
    {
      "component_id": "L2",
      "timestamp_utc": "2026-10-29T10:00:00Z",
      "latency_ms": 180.0,
      "packet_loss_pct": 25.0,
      "throughput_mbps": null,
      "connectivity_ok": true
    }
  ]
}

These values are illustrative. Actual responses must contain
measurements produced by the testbed or measurement collector.
Unavailable values must be null, not fabricated.

## 8. List subscribers

GET /api/v1/subscribers

Response:
{
  "subscribers": [
    {
      "id": "SUB101",
      "display_name": "Demo Subscriber 101",
      "plan": "Basic",
      "access_point_id": "AP1",
      "status": "active",
      "payment_status": "paid",
      "due_date": "2026-11-01"
    }
  ]
}

Subscriber and payment records in the prototype may use
clearly labelled demo business data.

## 9. Record a payment reminder

POST /api/v1/subscribers/{subscriber_id}/remind

Request:
{
  "language": "hi"
}

Response:
{
  "subscriber_id": "SUB101",
  "status": "recorded",
  "delivery_status": "not_sent"
}

The initial prototype records a reminder action.
It must not claim an SMS or WhatsApp message was delivered
unless a real messaging integration confirms delivery.

## 10. Explain an incident in Hindi

POST /api/v1/incidents/{incident_id}/explain

Request:
{
  "language": "hi"
}

Response:
{
  "incident_id": "incident-001",
  "language": "hi",
  "explanation": "Hindi explanation based on verified incident data",
  "provider": "sarvam"
}

Use Sarvam for the language interaction. The explanation
must be grounded in the actual incident result, not invented
measurements or subscriber counts.

## Shared implementation rules

1. Neo4j stores network topology and relationships.
2. The graph engine performs fault localization and dependency analysis.
3. FastAPI exposes the API contract above.
4. SQLite stores initial operational records.
5. React and TypeScript consume API responses.
6. Sarvam explains verified application results.
7. All timestamps use ISO 8601 UTC.
8. Missing measurements must remain null.
9. Simulated and measured data must be clearly distinguished.
10. API keys and credentials must never be committed to GitHub.

All members must communicate contract changes before
implementing incompatible interfaces.