# HopTrace Test Counts & Quality Gate Report

Generated at: 2026-11-21 17:30 IST  
Branch: `feat/neo4j-n1-n2`  
Integrated Tracks: N0–N2 (Neo4j Graph Database Integration) & B1 (Subscriber Outage & Restoration Notification Flow)

---

## Executive Summary

| Test Suite | Total Tests | Passed | Failed | Skipped | Pass Rate | Execution Time |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Backend Unit, Integration & Predictive Benchmarks (pytest)** | 339 | **334** | 0 | 5* | **100%** | ~14.8s |
| **Frontend Unit Tests (node --test)** | 68 | **68** | 0 | 0 | **100%** | ~0.18s |
| **Frontend Code Quality (ESLint)** | All files | **0 errors** | 0 warnings | - | **100%** | ~15s |
| **Combined Full-Stack Total** | **407** | **402** | **0** | **5** | **100%** | - |

*\*Note on Skipped Tests (5 tests):*  
All 5 skipped tests are live Neo4j Aura database integration and parity tests (`@pytest.mark.integration` in `tests/engine/test_neo4j_integration.py` and `tests/engine/test_graph_n2_parity.py`). They skip cleanly when `NEO4J_URI` is not configured, and execute automatically against a live Neo4j Aura or container instance when credentials are provided.

---

## 1. Backend Test Breakdown (`python -m pytest tests -v`) — 339 Tests

### Track B1: Outage & Restoration Notification Flow (`tests/api/test_b1_notify_flow.py`) - 10 Tests PASS
- `test_parallel_sends_atomic_idempotency_claim`: Parallel sends and atomic SQLite idempotency claim (no duplicate dispatch, UNIQUE constraint safe)
- `test_failed_send_retry`: Failed send retry (failed row is re-claimed and updated to sent)
- `test_resend_after_phone_correction`: Resend after phone correction (skipped invalid_e164_phone re-claimed and sent)
- `test_provider_error_mid_batch_does_not_abort`: Provider error mid-batch (sub 1 sent, sub 2 failed, sub 3 sent; batch does not abort)
- `test_simulated_incident_with_twilio_configured_is_blocked`: Simulated incident with Twilio configured (Twilio call blocked, skipped with simulated_incident_twilio_blocked)
- `test_twilio_allowlist_enforcement`: Allowlist enforcement (NOTIFY_ALLOWLIST allows listed numbers, skips others with not_in_allowlist)
- `test_phone_masking_in_preview_and_history`: Phone masking in all GET responses (/preview and /notifications)
- `test_preview_works_when_unconfigured_while_send_returns_503`: Preview when unconfigured (returns HTTP 200, only POST /notify returns HTTP 503)
- `test_restoration_defaults_to_subscribers_sent_outage`: Restoration default recipient filtering (defaults to subscribers sent outage message)
- `test_max_recipients_cap`: Max recipients cap enforcement (NOTIFY_MAX_RECIPIENTS)

### Agent Tests (`tests/agent/`) - 15 Tests
- `tests/agent/test_agent_field_hardening.py`:
  - `test_agent_preflight_check_flag`: PASS (parallel node & backend API probing)
  - `test_agent_exponential_backoff`: PASS (resilience against backend outage)
  - `test_agent_ping_jitter_extraction`: PASS (mdev / jitter extraction)
  - `test_agent_graceful_shutdown`: PASS (SIGINT / SIGTERM clean exit)
- `tests/agent/test_hoptrace_agent.py`: 11 tests PASS (synthetic ping, traceroute, JSON telemetry upload)

### Predictive ML & Benchmark Tests (`tests/engine/test_predictor.py`, `tests/test_benchmark_smoke.py`, etc.) - 38 Tests
- `tests/engine/test_predictor.py`: Theil-Sen estimator, robust degradation trend modeling, lead time calculation (12 tests)
- `tests/engine/test_realistic_scenarios.py`: Stochastic noise generation, gradual degradation ramps (10 tests)
- `tests/engine/test_replay.py`: CSV real telemetry data replay adapter (8 tests)
- `tests/test_benchmark_smoke.py`: Benchmark runner, comparative evaluation vs EWMA and static thresholds (8 tests)

### API Tests (`tests/api/`) - 113 Tests
- `test_agents.py`: Agent registration, heartbeat, and offline TTL tracking (5 tests)
- `test_auth.py`: Token generation, validation, and rejection (6 tests)
- `test_explanations.py`: Sarvam LLM, Bulbul TTS audio, fallback simulation (8 tests)
- `test_graph_incident_api.py`: Graph incident intelligence (9 tests PASS)
  - `test_get_incident_graph_404_not_found`: 404 on missing incidents
  - `test_get_incident_graph_simulated_incident`: Simulated incidents use in-memory store
  - `test_get_incident_graph_no_phone_numbers_leaked`: Zero phone numbers in API response
  - `test_get_incident_graph_essential_services_sorted_first`: Priority restore sorting
  - `test_get_incident_graph_handles_failed_node`: Support for failed nodes as well as links
  - `test_get_incident_graph_live_source_fallback_when_neo4j_down`: Safe memory fallback with fallback: true
  - `test_notify_reconciliation_logs_warning_and_filters_unreconciled`: Forward SQLite reconciliation
  - `test_incident_history_counts_only_live_incidents`: Chronic fault query filters data_source = 'live'
  - `test_notify_reconciliation_reverse_direction_includes_extra_sqlite_subscriber`: Two-way reconciliation
- `test_incidents.py`: Incident creation, state transitions, resolution (12 tests)
- `test_measurements_ingest.py`: High-throughput metric ingestion & validation (14 tests)
- `test_notifications.py`: Outage alert dispatch and preview (10 tests)
- `test_probes_api.py`: Probing paths, cycle detection, synthetic hop simulation (10 tests)
- `test_security.py`: Rate limiting, XSS prevention, CORS policy, header hardening (8 tests)
- `test_subscribers.py`: Subscriber CRUD, payment status, QR payload (9 tests)
- `test_telemetry_ws_live.py`: WebSocket broadcast, live streaming, reconnection (12 tests)
- `test_topology.py` & `test_topology_v2.py`: GIS endpoints, geo-coordinates, predictive risk endpoints, SLA metrics (20 tests)

### Engine & Analytics Tests (`tests/engine/`) - 161 Tests
- `test_graph_backend_n1.py`: Safe Neo4j activation & fallback (8 tests PASS)
  - `test_graph_backend_memory_always_in_memory`: GRAPH_BACKEND=memory isolation
  - `test_negative_cache_availability_probe`: 30s backoff negative cache
  - `test_topology_cache_locked_and_invalidated_on_seed`: Thread-safe cached snapshot
  - `test_mid_run_neo4j_failure_falls_back_without_500`: Mid-run crash resilience
  - `test_sanitize_last_error_removes_uri_user_password`: Generic error summaries
  - `test_get_graph_status_endpoint_offline`: Status endpoint reporting
  - `test_get_graph_status_endpoint_unconfigured`: Clean unconfigured state
  - `test_get_graph_status_endpoint_memory_mode`: Forced memory backend status
- `test_graph_n2_parity.py`: Neo4j vs In-Memory Parity & Incident Writeback (3 tests, skipped without live Aura)
  - `test_link_failure_parity`: Link failure blast-radius parity
  - `test_node_failure_parity`: Node failure blast-radius parity
  - `test_record_incident_node_and_affected_relationships_live`: Incident write & readback
- `test_neo4j_client.py`: Neo4j driver & query sanitization (8 tests)
- `test_neo4j_integration.py`: Live Neo4j topology integration (2 tests, skipped without live Aura)
- `test_baselines_learned.py`: EWMA baselines persistence in SQLite across server restarts (7 tests)
- `test_cause.py`: Root Cause Analysis, graph traversal, and fault isolation (16 tests)
- `test_diagnostics.py`: Anomaly z-scoring, network jitter, loss attribution (24 tests)
- `test_incident_persistence.py`: DB schema persistence, event log journaling (11 tests)
- `test_incident_sla.py`: Village SLA uptime %, outage duration, penalty calculations (5 tests)
- `test_live_ttl.py`: Stale telemetry decay and connectivity timeouts (8 tests)
- `test_predictive.py`: Linear regression failure prediction, risk ETA derivation (18 tests)
- `test_probes_derivation.py`: Active probing path selection, hop matrix (12 tests)
- Remaining engine and mathematical model tests: (37 tests)

### Demo Runner Tests - 2 Tests
- `tests/test_demo_runner.py`: End-to-end multi-phase judging scenario simulation (2 tests)

---

## 2. Frontend Test Breakdown (`node --test ...`) - 68 Tests

### Network Status Banner & Operations (`frontend/src/components/NetworkStatusBanner.test.js`) - 11 Tests
- `formatElapsed`: Elapsed time calculations, formatting seconds, minutes, and hours.
- `formatRevenue`: Indian Rupee INR localized currency formatting.
- `getNextStep`: Actionable next steps derived from field operator recommendations, AI explanations, and diagnostic heuristic fallbacks.

### View Preferences & Storage (`frontend/src/components/NetworkView/viewPref.test.js`) - 6 Tests
- Default view recovery, valid storage retrieval, fallback on invalid storage, fault tolerance when `localStorage` throws.

### GIS Map Model & Bounds (`frontend/src/components/VillageMap/*.test.js`) - 28 Tests
- `computeBounds`: Bounding box calculation, non-finite lat/lon handling.
- `parseGHz` & `fresnelF1Metres`: Exact 60% first Fresnel zone clearance for links L3, L7, and L12.
- `getLinkMidpoint` & `getPredictedEtaMinutes`: Midpoint and risk ETA badge formatting.
- `getNodeIconConfig` & `getSuspectedRingConfig`: Distinct SVG/DivIcon markers, suspected rings, blast radius badges.
- `buildMapModel`: Healthy baseline, L3 degradation, suspected link/blast APs, instant clearing upon incident resolution.
- `buildFailurePath`: Tree traversal from gateway GW1 down to leaf wireless APs.

### Layer Controls & Telemetry History (`frontend/src/lib/*.test.js`) - 23 Tests
- `riskColor`: Threshold verification (nominal, elevated, critical).
- `getLinkRisk`: Score precedence hierarchy (snapshot > liveMap > fallback).
- `getLinkDashArray` & `getLinkStrokeWidth`: Visual styling and dashed stroke rules.
- `villageStatusColor`: Backend status mapping for Rampur, Bhatpur, and Daulatpur.
- `freshnessStyle`, `formatLastSeen`, `isHealthyForKpi`: Real-time data freshness monitoring.
- `buildFailurePath`: Graph tree traversal and degraded hop isolation.

---

## 3. Screenshots Archived

1. `screenshots/noc_dashboard.jpg` - NOC Operations Cockpit (Leaflet GIS, live telemetry history, signal loss/jitter/throughput, node status).
2. `screenshots/business_dashboard.jpg` - Business & Revenue Impact (Village coverage, SLA credit compensation monitor, Kirana subscriber operations).
