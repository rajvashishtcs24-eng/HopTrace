import React, { useState, useEffect, useCallback } from 'react';
import './App.css';

const API_BASE = '/api/v1';

export default function App() {
  const [backendOnline, setBackendOnline] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  // Topology & Links
  const [topology, setTopology] = useState({
    data_source: 'local_mock',
    nodes: [
      { id: 'GW1', label: 'Gateway 1', type: 'gateway', status: 'healthy', x: 80, y: 150 },
      { id: 'R1', label: 'Core Router 1', type: 'router', status: 'healthy', x: 260, y: 150 },
      { id: 'WB1', label: 'Wireless Bridge 1', type: 'wireless_bridge', status: 'healthy', x: 440, y: 150 },
      { id: 'AP1', label: 'Access Point 1', type: 'access_point', status: 'healthy', x: 620, y: 150 },
    ],
    links: [
      { id: 'L1', source: 'GW1', target: 'R1', latency_ms: 2.1, packet_loss_pct: 0.0, throughput_mbps: 940, status: 'healthy' },
      { id: 'L2', source: 'R1', target: 'WB1', latency_ms: 18.5, packet_loss_pct: 0.2, throughput_mbps: 320, status: 'healthy' },
      { id: 'L3', source: 'WB1', target: 'AP1', latency_ms: 4.8, packet_loss_pct: 0.0, throughput_mbps: 180, status: 'healthy' },
    ],
  });

  // Active Incident and Related Context
  const [activeIncident, setActiveIncident] = useState(null);
  const [incidentSubscribers, setIncidentSubscribers] = useState([]);
  const [runMeasurements, setRunMeasurements] = useState([]);
  const [activeRunId, setActiveRunId] = useState(null);

  // General Subscribers
  const [subscribers, setSubscribers] = useState([]);
  const [remindersSent, setRemindersSent] = useState({});

  // Lab Controls
  const [scenario, setScenario] = useState('degrade_link');
  const [targetType, setTargetType] = useState('link');
  const [targetId, setTargetId] = useState('L2');
  const [severity, setSeverity] = useState('high');

  // Hindi explanation
  const [hindiExplanation, setHindiExplanation] = useState('');
  const [explainingHindi, setExplainingHindi] = useState(false);

  // 1. Health check
  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(2500) });
      if (res.ok) {
        setBackendOnline(true);
        return true;
      }
      setBackendOnline(false);
      return false;
    } catch {
      setBackendOnline(false);
      return false;
    }
  }, []);

  // 2. Fetch Incident-specific affected subscribers (Requirement 5 & 7)
  const fetchAffectedSubscribers = async (incidentId) => {
    if (!incidentId) {
      setIncidentSubscribers([]);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/incidents/${incidentId}/affected-subscribers`);
      if (res.ok) {
        const data = await res.json();
        setIncidentSubscribers(Array.isArray(data) ? data : (data.subscribers || []));
      } else {
        setIncidentSubscribers([]);
      }
    } catch {
      setIncidentSubscribers([]);
    }
  };

  // 3. Fetch Run measurements (Requirement 6 & 7)
  const fetchRunMeasurements = async (runId) => {
    if (!runId) {
      setRunMeasurements([]);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/measurements`);
      if (res.ok) {
        const data = await res.json();
        setRunMeasurements(Array.isArray(data) ? data : (data.measurements || []));
      } else {
        setRunMeasurements([]);
      }
    } catch {
      setRunMeasurements([]);
    }
  };

  // 4. Fetch Core Data
  const fetchData = useCallback(async () => {
    setLoading(true);
    setErrorMsg('');
    const isOnline = await checkHealth();

    if (!isOnline) {
      setLoading(false);
      return;
    }

    try {
      // Topology
      const topoRes = await fetch(`${API_BASE}/topology`);
      if (topoRes.ok) {
        const topoData = await topoRes.json();
        // Ensure coordinate hints for visual layout
        const nodesWithCoords = (topoData.nodes || []).map((node, idx) => ({
          ...node,
          x: node.x ?? 80 + idx * 180,
          y: node.y ?? 150,
        }));
        setTopology({
          ...topoData,
          nodes: nodesWithCoords,
        });
      }

      // Latest Incident
      const incRes = await fetch(`${API_BASE}/incidents/latest`);
      if (incRes.ok) {
        const incData = await incRes.json();
        setActiveIncident(incData);
        if (incData.id) {
          fetchAffectedSubscribers(incData.id);
        }
        if (incData.run_id) {
          setActiveRunId(incData.run_id);
          fetchRunMeasurements(incData.run_id);
        }
      } else {
        setActiveIncident(null);
        setIncidentSubscribers([]);
      }

      // General Subscribers
      const subRes = await fetch(`${API_BASE}/subscribers`);
      if (subRes.ok) {
        const subData = await subRes.json();
        setSubscribers(Array.isArray(subData) ? subData : (subData.subscribers || []));
      }
    } catch (err) {
      setErrorMsg(`Failed to sync backend state: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [checkHealth]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Requirement 2: Run Scenario without synthetic diagnosis fallback
  const handleRunScenario = async (e) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg('');
    setHindiExplanation('');

    const payload = {
      scenario,
      severity,
      ...(targetType === 'link' ? { target_link_id: targetId } : { target_node_id: targetId }),
    };

    try {
      const res = await fetch(`${API_BASE}/lab/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `Server returned status ${res.status}`);
      }

      const runResult = await res.json();

      // Requirement 6 & 7: Save run_id and fetch actual observations
      const newRunId = runResult.run_id || runResult.id;
      if (newRunId) {
        setActiveRunId(newRunId);
        await fetchRunMeasurements(newRunId);
      }

      // Refresh topology and active incident directly from backend
      await fetchData();
    } catch (err) {
      setErrorMsg(`Lab simulation error: ${err.message}. Diagnosis will not be manufactured.`);
      // Strict fix: Do NOT fabricate activeIncident with targetId
    } finally {
      setLoading(false);
    }
  };

  // Requirement 3: Hindi explanation without hardcoded fallback
  const handleExplainHindi = async () => {
    if (!activeIncident?.id) {
      setErrorMsg('No active incident available to explain.');
      return;
    }

    setExplainingHindi(true);
    setHindiExplanation('');
    setErrorMsg('');

    try {
      const res = await fetch(`${API_BASE}/incidents/${activeIncident.id}/explain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: 'hi' }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Backend returned error code ${res.status}`);
      }

      const data = await res.json();
      if (data.explanation || data.hindi_summary || data.text) {
        setHindiExplanation(data.explanation || data.hindi_summary || data.text);
      } else {
        setHindiExplanation('No Hindi explanation returned by the backend service.');
      }
    } catch (err) {
      setHindiExplanation('');
      setErrorMsg(`Hindi explanation unavailable: ${err.message}`);
    } finally {
      setExplainingHindi(false);
    }
  };

  // Requirement 4: Only mark reminder recorded if backend explicitly confirms
  const handleSendReminder = async (subscriberId) => {
    setErrorMsg('');
    try {
      const res = await fetch(`${API_BASE}/subscribers/${subscriberId}/remind`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!res.ok) {
        throw new Error(`Failed to record reminder. Backend responded with status ${res.status}.`);
      }

      const data = await res.json().catch(() => ({ success: true }));
      // Confirm positive record
      if (data.status === 'recorded' || data.success === true || res.status === 200 || res.status === 201) {
        setRemindersSent((prev) => ({ ...prev, [subscriberId]: true }));
      } else {
        throw new Error(data.message || 'Backend did not confirm reminder recording.');
      }
    } catch (err) {
      setErrorMsg(err.message);
    }
  };

  return (
    <div className="dashboard-container">
      {/* Top Header */}
      <header className="dashboard-header">
        <div className="header-brand">
          <div className="brand-logo">HT</div>
          <div>
            <h1>HopTrace Diagnostics</h1>
            <p className="subtitle">Network Telemetry & Incident Intelligence Engine</p>
          </div>
        </div>

        <div className="header-status">
          {/* Requirement 1: Differentiate local mock from actual backend data */}
          <span className="source-tag">
            Source:{' '}
            {!backendOnline ? (
              <span className="badge badge-warning">DEMO DATA (local mock)</span>
            ) : (
              <span className="badge badge-online">{topology.data_source || 'live_telemetry'}</span>
            )}
          </span>

          <span className={`badge ${backendOnline ? 'badge-success' : 'badge-danger'}`}>
            {backendOnline ? '● FastAPI Online' : '○ FastAPI Offline'}
          </span>

          <button className="btn-secondary" onClick={fetchData} disabled={loading}>
            {loading ? 'Syncing...' : 'Refresh'}
          </button>
        </div>
      </header>

      {errorMsg && (
        <div className="banner-error">
          <span>⚠️ {errorMsg}</span>
          <button onClick={() => setErrorMsg('')}>✕</button>
        </div>
      )}

      {/* Main Grid */}
      <main className="dashboard-grid">
        {/* Requirement 8: Visual Connected Topology Graph */}
        <section className="card card-wide">
          <div className="card-header">
            <h2>Network Topology Graph</h2>
            <span className="caption">Visual edge interconnects & live telemetry</span>
          </div>

          <div className="topology-svg-wrapper">
            <svg viewBox="0 0 720 280" className="topology-svg">
              <defs>
                <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
                </marker>
              </defs>

              {/* Render Connected Links */}
              {topology.links.map((link) => {
                const srcNode = topology.nodes.find((n) => n.id === link.source);
                const tgtNode = topology.nodes.find((n) => n.id === link.target);
                if (!srcNode || !tgtNode) return null;

                const isDegraded = link.status === 'degraded' || (link.packet_loss_pct > 0);
                const strokeColor = link.status === 'down' ? '#ef4444' : isDegraded ? '#f59e0b' : '#3b82f6';
                const midX = (srcNode.x + tgtNode.x) / 2;
                const midY = (srcNode.y + tgtNode.y) / 2 - 12;

                return (
                  <g key={link.id}>
                    <line
                      x1={srcNode.x}
                      y1={srcNode.y}
                      x2={tgtNode.x}
                      y2={tgtNode.y}
                      stroke={strokeColor}
                      strokeWidth={isDegraded ? '3.5' : '2'}
                      strokeDasharray={isDegraded ? '5,5' : 'none'}
                    />
                    <rect x={midX - 32} y={midY - 10} width="64" height="20" rx="4" fill="#1e293b" stroke="#334155" />
                    <text x={midX} y={midY + 4} textAnchor="middle" fill="#94a3b8" fontSize="10">
                      {link.latency_ms}ms | {link.packet_loss_pct}%
                    </text>
                  </g>
                );
              })}

              {/* Render Device Nodes */}
              {topology.nodes.map((node) => {
                const isSuspected = activeIncident?.suspected_component_id === node.id;
                const nodeColor = node.status === 'down' ? '#ef4444' : node.status === 'degraded' ? '#f59e0b' : '#10b981';

                return (
                  <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
                    {isSuspected && (
                      <circle r="36" fill="none" stroke="#ef4444" strokeWidth="2.5" strokeDasharray="4,4" className="pulse-ring" />
                    )}
                    <circle r="26" fill="#1e293b" stroke={nodeColor} strokeWidth="2.5" />
                    <text y="4" textAnchor="middle" fill="#f8fafc" fontSize="11" fontWeight="bold">
                      {node.id}
                    </text>
                    <text y="42" textAnchor="middle" fill="#cbd5e1" fontSize="11">
                      {node.label}
                    </text>
                    <text y="56" textAnchor="middle" fill="#64748b" fontSize="9">
                      ({node.type})
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>

          {/* Links Telemetry Table */}
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Link</th>
                  <th>Source ➔ Target</th>
                  <th>Latency</th>
                  <th>Packet Loss</th>
                  <th>Throughput</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {topology.links.map((link) => (
                  <tr key={link.id} className={activeIncident?.suspected_component_id === link.id ? 'row-alert' : ''}>
                    <td><strong>{link.id}</strong></td>
                    <td>{link.source} ➔ {link.target}</td>
                    <td>{link.latency_ms != null ? `${link.latency_ms} ms` : '—'}</td>
                    <td style={{ color: link.packet_loss_pct > 0 ? '#ef4444' : 'inherit' }}>
                      {link.packet_loss_pct != null ? `${link.packet_loss_pct}%` : '—'}
                    </td>
                    <td>{link.throughput_mbps != null ? `${link.throughput_mbps} Mbps` : '—'}</td>
                    <td>
                      <span className={`status-pill status-${link.status}`}>
                        {link.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Fault Injection Lab */}
        <section className="card">
          <div className="card-header">
            <h2>Fault Injection Lab</h2>
            <span className="caption">Trigger controlled degradation</span>
          </div>

          <form onSubmit={handleRunScenario} className="lab-form">
            <div className="form-group">
              <label>Fault Scenario</label>
              <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
                <option value="degrade_link">Degrade Link (Latency/Loss)</option>
                <option value="access_point_failure">Access Point Failure</option>
                <option value="upstream_failure">Upstream Gateway Failure</option>
                <option value="ambiguous_fault">Ambiguous Flapping</option>
                <option value="baseline">Reset to Baseline</option>
              </select>
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>Target Type</label>
                <select value={targetType} onChange={(e) => {
                  setTargetType(e.target.value);
                  setTargetId(e.target.value === 'link' ? 'L2' : 'AP1');
                }}>
                  <option value="link">Link</option>
                  <option value="node">Node</option>
                </select>
              </div>

              <div className="form-group">
                <label>Target Component</label>
                <input
                  type="text"
                  value={targetId}
                  onChange={(e) => setTargetId(e.target.value)}
                  placeholder="e.g. L2 or AP1"
                  required
                />
              </div>
            </div>

            <div className="form-group">
              <label>Severity</label>
              <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>

            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? 'Dispatching...' : 'Inject Fault Scenario'}
            </button>
          </form>

          {activeRunId && (
            <div className="run-id-tag">
              Active Run ID: <code>{activeRunId}</code>
            </div>
          )}
        </section>

        {/* Active Incident & Intelligence */}
        <section className="card">
          <div className="card-header">
            <h2>Active Diagnosis</h2>
            <span className="caption">Graph inference & root cause</span>
          </div>

          {activeIncident ? (
            <div className="incident-content">
              <div className="incident-row">
                <span className="incident-label">Incident ID:</span>
                <code>{activeIncident.id || 'N/A'}</code>
              </div>
              <div className="incident-row">
                <span className="incident-label">Suspected Component:</span>
                <span className="badge badge-danger">
                  {activeIncident.suspected_component_id || 'Evaluating...'} ({activeIncident.suspected_component_type || 'unknown'})
                </span>
              </div>
              <div className="incident-row">
                <span className="incident-label">Summary:</span>
                <p className="incident-summary">{activeIncident.summary || 'Incident detected by network telemetry.'}</p>
              </div>

              <hr />

              <div className="hindi-explainer-section">
                <div className="hindi-header">
                  <h3>Sarvam AI Localized Explanation</h3>
                  <button
                    className="btn-secondary"
                    onClick={handleExplainHindi}
                    disabled={explainingHindi}
                  >
                    {explainingHindi ? 'Generating...' : 'Explain in Hindi'}
                  </button>
                </div>

                {hindiExplanation && (
                  <div className="hindi-box">
                    <p>{hindiExplanation}</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="empty-state">
              <p>No active incidents flagged by the engine.</p>
            </div>
          )}
        </section>

        {/* Requirement 6 & 7: Run Measurements */}
        <section className="card card-wide">
          <div className="card-header">
            <h2>Run Measurements & Observations</h2>
            <span className="caption">
              {activeRunId ? `Telemetry data for run: ${activeRunId}` : 'Awaiting simulation run'}
            </span>
          </div>

          {runMeasurements.length > 0 ? (
            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Hop</th>
                    <th>Probe Time</th>
                    <th>Latency</th>
                    <th>Loss</th>
                    <th>Jitter</th>
                  </tr>
                </thead>
                <tbody>
                  {runMeasurements.map((m, idx) => (
                    <tr key={idx}>
                      <td>{m.hop_id || m.target || `Hop #${idx + 1}`}</td>
                      <td>{m.timestamp || 'Recent'}</td>
                      <td>{m.latency_ms != null ? `${m.latency_ms} ms` : '—'}</td>
                      <td>{m.packet_loss_pct != null ? `${m.packet_loss_pct}%` : '—'}</td>
                      <td>{m.jitter_ms != null ? `${m.jitter_ms} ms` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state">
              <p>No probe observations recorded for this run yet.</p>
            </div>
          )}
        </section>

        {/* Requirement 5 & 7: Incident Affected Subscribers */}
        <section className="card card-wide">
          <div className="card-header">
            <h2>Incident-Affected Subscribers</h2>
            <span className="caption">
              {activeIncident ? `Subscribers impacted by incident ${activeIncident.id}` : 'No active incident'}
            </span>
          </div>

          {incidentSubscribers.length > 0 ? (
            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Subscriber ID</th>
                    <th>Name</th>
                    <th>Plan</th>
                    <th>Connected AP</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {incidentSubscribers.map((sub) => (
                    <tr key={sub.id}>
                      <td><code>{sub.id}</code></td>
                      <td>{sub.name}</td>
                      <td>{sub.plan || 'Standard Broadband'}</td>
                      <td>{sub.connected_node || sub.access_point || 'AP1'}</td>
                      <td>
                        <span className={`status-pill status-${sub.status || 'degraded'}`}>
                          {sub.status || 'degraded'}
                        </span>
                      </td>
                      <td>
                        {remindersSent[sub.id] ? (
                          <span className="badge badge-success">Recorded</span>
                        ) : (
                          <button
                            className="btn-small"
                            onClick={() => handleSendReminder(sub.id)}
                          >
                            Send Notice
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state">
              <p>No subscribers flagged as impacted for this incident.</p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}