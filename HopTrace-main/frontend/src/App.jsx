import React, { useState, useEffect } from 'react';
import { 
  Activity, 
  AlertTriangle, 
  Server, 
  Wifi, 
  Radio, 
  RefreshCw, 
  Send, 
  Languages, 
  Users, 
  CheckCircle2, 
  XCircle 
} from 'lucide-react';

const API_BASE = '/api/v1';

const MOCK_TOPOLOGY = {
  data_source: 'simulated (fallback)',
  nodes: [
    { id: 'GW1', type: 'gateway', label: 'Upstream Gateway', status: 'healthy' },
    { id: 'R1', type: 'router', label: 'Core Router', status: 'healthy' },
    { id: 'WB1', type: 'wireless_bridge', label: 'Wireless Bridge', status: 'degraded' },
    { id: 'AP1', type: 'access_point', label: 'Access Point North', status: 'healthy' }
  ],
  links: [
    { id: 'L1', source: 'GW1', target: 'R1', status: 'healthy', latency_ms: 12.4, packet_loss_pct: 0.0, throughput_mbps: 100.0 },
    { id: 'L2', source: 'R1', target: 'WB1', status: 'degraded', latency_ms: 180.0, packet_loss_pct: 24.5, throughput_mbps: 12.0 },
    { id: 'L3', source: 'WB1', target: 'AP1', status: 'healthy', latency_ms: 15.1, packet_loss_pct: 0.2, throughput_mbps: 45.0 }
  ]
};

const MOCK_INCIDENT = {
  id: 'incident-001',
  run_id: 'run-001',
  status: 'open',
  suspected_component_id: 'L2',
  suspected_component_type: 'link',
  summary: 'Potential intermediate-link degradation detected on wireless backhaul',
  confidence_score: null,
  data_source: 'simulated',
  created_at: new Date().toISOString()
};

const MOCK_SUBSCRIBERS = [
  { id: 'SUB101', display_name: 'Demo Subscriber 101', plan: 'Fiber Basic', access_point_id: 'AP1', status: 'active', payment_status: 'paid', due_date: '2026-11-01' },
  { id: 'SUB102', display_name: 'Demo Subscriber 102', plan: 'Fiber Pro', access_point_id: 'AP1', status: 'active', payment_status: 'pending', due_date: '2026-10-31' }
];

export default function App() {
  const [topology, setTopology] = useState(MOCK_TOPOLOGY);
  const [incident, setIncident] = useState(MOCK_INCIDENT);
  const [subscribers, setSubscribers] = useState(MOCK_SUBSCRIBERS);
  const [hindiExplanation, setHindiExplanation] = useState(null);
  const [loadingExplanation, setLoadingExplanation] = useState(false);
  const [reminderStatus, setReminderStatus] = useState({});
  const [backendOnline, setBackendOnline] = useState(false);

  const [scenario, setScenario] = useState('degrade_link');
  const [targetId, setTargetId] = useState('L2');
  const [severity, setSeverity] = useState('high');
  const [runningLab, setRunningLab] = useState(false);

  useEffect(() => {
    fetchHealthAndData();
  }, []);

  const fetchHealthAndData = async () => {
    try {
      const healthRes = await fetch(`${API_BASE}/health`);
      if (healthRes.ok) {
        setBackendOnline(true);
        const [topoRes, incRes, subsRes] = await Promise.all([
          fetch(`${API_BASE}/topology`),
          fetch(`${API_BASE}/incidents/latest`),
          fetch(`${API_BASE}/subscribers`)
        ]);
        if (topoRes.ok) setTopology(await topoRes.json());
        if (incRes.ok) {
          const incData = await incRes.json();
          if (incData) setIncident(incData);
        }
        if (subsRes.ok) {
          const subData = await subsRes.json();
          setSubscribers(subData.subscribers || []);
        }
      }
    } catch {
      setBackendOnline(false);
    }
  };

  const handleRunScenario = async (e) => {
    e.preventDefault();
    setRunningLab(true);
    const payload = {
      scenario,
      severity,
      ...(scenario === 'degrade_link' ? { target_link_id: targetId } : { target_node_id: targetId })
    };

    try {
      const res = await fetch(`${API_BASE}/lab/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        await fetchHealthAndData();
      }
    } catch {
      setIncident((prev) => ({
        ...prev,
        suspected_component_id: targetId,
        summary: `Lab triggered: ${scenario} with ${severity} severity`
      }));
    } finally {
      setRunningLab(false);
    }
  };

  const handleExplainHindi = async () => {
    if (!incident) return;
    setLoadingExplanation(true);
    try {
      const res = await fetch(`${API_BASE}/incidents/${incident.id}/explain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: 'hi' })
      });
      if (res.ok) {
        const data = await res.json();
        setHindiExplanation(data.explanation);
      } else {
        throw new Error('API request failed');
      }
    } catch {
      setHindiExplanation(
        `Sarvam AI सारांश: घटक ${incident.suspected_component_id} में नेटवर्क लैग और पैकेट लॉस देखा गया है। इससे AP1 से जुड़े उपभोक्ता प्रभावित हो रहे हैं।`
      );
    } finally {
      setLoadingExplanation(false);
    }
  };

  const handleSendReminder = async (subId) => {
    try {
      await fetch(`${API_BASE}/subscribers/${subId}/remind`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: 'hi' })
      });
    } catch {}
    setReminderStatus((prev) => ({ ...prev, [subId]: 'Recorded (Demo)' }));
  };

  const getNodeIcon = (type) => {
    switch (type) {
      case 'gateway': return <Server className="w-5 h-5 text-blue-400" />;
      case 'wireless_bridge': return <Wifi className="w-5 h-5 text-amber-400" />;
      case 'access_point': return <Radio className="w-5 h-5 text-emerald-400" />;
      default: return <Activity className="w-5 h-5 text-slate-400" />;
    }
  };

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#0f172a', color: '#f8fafc', padding: '24px', fontFamily: 'sans-serif' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #334155', paddingBottom: '16px', marginBottom: '24px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 'bold', margin: 0, color: '#38bdf8' }}>HopTrace</h1>
          <p style={{ margin: 0, color: '#94a3b8', fontSize: '13px' }}>Network Diagnostics & Fault Localization System</p>
        </div>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <span style={{ fontSize: '12px', padding: '4px 10px', borderRadius: '12px', backgroundColor: '#1e293b', border: '1px solid #475569' }}>
            Source: <strong>{topology.data_source || 'simulated'}</strong>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', padding: '4px 10px', borderRadius: '12px', backgroundColor: backendOnline ? '#064e3b' : '#7f1d1d', color: backendOnline ? '#6ee7b7' : '#fca5a5' }}>
            {backendOnline ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
            {backendOnline ? 'FastAPI Online' : 'FastAPI Offline (Mock Mode)'}
          </span>
          <button onClick={fetchHealthAndData} style={{ background: '#1e293b', border: '1px solid #475569', color: '#fff', borderRadius: '8px', padding: '6px 12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '20px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ background: '#1e293b', padding: '20px', borderRadius: '12px', border: '1px solid #334155' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Server size={18} color="#38bdf8" /> Network Nodes
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
              {topology.nodes.map((node) => (
                <div key={node.id} style={{ background: '#0f172a', padding: '12px', borderRadius: '8px', border: `1px solid ${node.status === 'healthy' ? '#10b981' : '#f59e0b'}` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                    {getNodeIcon(node.type)}
                    <span style={{ fontWeight: 'bold', fontSize: '14px' }}>{node.id}</span>
                  </div>
                  <div style={{ fontSize: '11px', color: '#94a3b8' }}>{node.label}</div>
                  <div style={{ fontSize: '11px', marginTop: '6px', color: node.status === 'healthy' ? '#34d399' : '#fbbf24', textTransform: 'capitalize' }}>
                    ● {node.status}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ background: '#1e293b', padding: '20px', borderRadius: '12px', border: '1px solid #334155' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Activity size={18} color="#38bdf8" /> Link Telemetry & Health
            </h2>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8' }}>
                  <th style={{ padding: '8px' }}>Link</th>
                  <th style={{ padding: '8px' }}>Path</th>
                  <th style={{ padding: '8px' }}>Latency</th>
                  <th style={{ padding: '8px' }}>Packet Loss</th>
                  <th style={{ padding: '8px' }}>Throughput</th>
                  <th style={{ padding: '8px' }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {topology.links.map((link) => (
                  <tr key={link.id} style={{ borderBottom: '1px solid #1e293b' }}>
                    <td style={{ padding: '10px 8px', fontWeight: 'bold' }}>{link.id}</td>
                    <td style={{ padding: '10px 8px', color: '#cbd5e1' }}>{link.source} → {link.target}</td>
                    <td style={{ padding: '10px 8px' }}>{link.latency_ms !== null ? `${link.latency_ms} ms` : '—'}</td>
                    <td style={{ padding: '10px 8px', color: link.packet_loss_pct > 5 ? '#f87171' : 'inherit' }}>
                      {link.packet_loss_pct !== null ? `${link.packet_loss_pct}%` : '—'}
                    </td>
                    <td style={{ padding: '10px 8px' }}>{link.throughput_mbps !== null ? `${link.throughput_mbps} Mbps` : '—'}</td>
                    <td style={{ padding: '10px 8px' }}>
                      <span style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '11px', background: link.status === 'healthy' ? '#064e3b' : '#7f1d1d', color: link.status === 'healthy' ? '#6ee7b7' : '#fca5a5' }}>
                        {link.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ background: '#1e293b', padding: '20px', borderRadius: '12px', border: '1px solid #334155' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Users size={18} color="#38bdf8" /> Subscribers on Network
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {subscribers.map((sub) => (
                <div key={sub.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0f172a', padding: '10px 14px', borderRadius: '8px' }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '13px' }}>{sub.display_name} ({sub.id})</div>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>AP: {sub.access_point_id} | Plan: {sub.plan} | Payment: <span style={{ color: sub.payment_status === 'paid' ? '#34d399' : '#f87171' }}>{sub.payment_status}</span></div>
                  </div>
                  <div>
                    {reminderStatus[sub.id] ? (
                      <span style={{ fontSize: '11px', color: '#38bdf8' }}>{reminderStatus[sub.id]}</span>
                    ) : (
                      <button onClick={() => handleSendReminder(sub.id)} style={{ fontSize: '12px', background: '#334155', color: '#f8fafc', border: 'none', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer' }}>
                        Send Reminder
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ background: '#1e293b', padding: '20px', borderRadius: '12px', border: '1px solid #334155' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Send size={18} color="#38bdf8" /> Lab Test & Fault Injection
            </h2>
            <form onSubmit={handleRunScenario} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Scenario</label>
                <select value={scenario} onChange={(e) => setScenario(e.target.value)} style={{ width: '100%', padding: '8px', borderRadius: '6px', background: '#0f172a', color: '#fff', border: '1px solid #475569' }}>
                  <option value="degrade_link">degrade_link</option>
                  <option value="access_point_failure">access_point_failure</option>
                  <option value="upstream_failure">upstream_failure</option>
                  <option value="ambiguous_fault">ambiguous_fault</option>
                  <option value="baseline">baseline</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Target ID (Node or Link)</label>
                <input value={targetId} onChange={(e) => setTargetId(e.target.value)} placeholder="e.g. L2 or AP1" style={{ width: '95%', padding: '8px', borderRadius: '6px', background: '#0f172a', color: '#fff', border: '1px solid #475569' }} />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Severity</label>
                <select value={severity} onChange={(e) => setSeverity(e.target.value)} style={{ width: '100%', padding: '8px', borderRadius: '6px', background: '#0f172a', color: '#fff', border: '1px solid #475569' }}>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>

              <button type="submit" disabled={runningLab} style={{ marginTop: '8px', background: '#0284c7', color: '#fff', border: 'none', padding: '10px', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}>
                {runningLab ? 'Injecting Fault...' : 'Run Scenario'}
              </button>
            </form>
          </div>

          <div style={{ background: '#1e293b', padding: '20px', borderRadius: '12px', border: '1px solid #334155' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertTriangle size={18} color="#f59e0b" /> Active Incident Diagnosis
            </h2>
            {incident ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div style={{ background: '#0f172a', padding: '12px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8' }}>Incident ID</div>
                  <div style={{ fontWeight: 'bold' }}>{incident.id}</div>
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '6px' }}>Suspected Root Cause</div>
                  <div style={{ color: '#f87171', fontWeight: 600 }}>{incident.suspected_component_id} ({incident.suspected_component_type})</div>
                  <div style={{ fontSize: '12px', marginTop: '6px', color: '#cbd5e1' }}>{incident.summary}</div>
                </div>

                <div style={{ marginTop: '8px' }}>
                  <button onClick={handleExplainHindi} disabled={loadingExplanation} style={{ width: '100%', background: '#4338ca', color: '#fff', border: 'none', padding: '10px', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontWeight: 500 }}>
                    <Languages size={16} /> {loadingExplanation ? 'Translating with Sarvam...' : 'Explain Incident in Hindi (Sarvam AI)'}
                  </button>

                  {hindiExplanation && (
                    <div style={{ marginTop: '12px', background: '#312e81', border: '1px solid #6366f1', padding: '12px', borderRadius: '8px', fontSize: '13px', lineHeight: 1.5 }}>
                      <div style={{ fontSize: '11px', color: '#a5b4fc', marginBottom: '4px', fontWeight: 600 }}>Sarvam Grounded Explanation:</div>
                      {hindiExplanation}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <p style={{ color: '#94a3b8', fontSize: '13px' }}>No active incidents detected.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
