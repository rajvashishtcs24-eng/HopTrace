import { useState, useEffect } from 'react';
import { useApi } from '../../hooks/useApi';
import {
  DEFAULT_CYPHER_QUERIES,
  formatGraphBackendBadge,
  countEssentialSubscribers,
  formatPathNodes,
} from './graphHelpers';

export default function GraphCard({ incidentId }) {
  const { fetchIncidentGraph } = useApi();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showCypher, setShowCypher] = useState(false);

  useEffect(() => {
    if (!incidentId) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);

    fetchIncidentGraph(incidentId)
      .then((res) => {
        if (!cancelled && res) {
          setData(res);
        }
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [incidentId, fetchIncidentGraph]);

  if (!incidentId) return null;

  const isNeo4j = data?.backend === 'neo4j' && !data?.fallback;
  const badgeConfig = formatGraphBackendBadge(data?.backend, data?.fallback);
  const blastCount = data?.blast_radius?.count ?? 0;
  const subscribers = data?.blast_radius?.subscribers || [];
  const essentialCount = countEssentialSubscribers(subscribers);
  const pathNodes = formatPathNodes(data?.path?.nodes);
  const historyCount = data?.history?.incidents_30d ?? 0;
  const linkId = data?.history?.link_id || 'Component';
  const queries = (data?.queries && data.queries.length > 0) ? data.queries : DEFAULT_CYPHER_QUERIES;

  return (
    <div
      data-testid="graph-insights-card"
      className="bg-[#0a1628] border border-slate-800 rounded-xl p-3 flex flex-col gap-2.5 transition-all shadow-sm"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-slate-800/80 pb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-cyan-400 text-sm">🕸️</span>
          <span className="text-xs font-semibold text-white tracking-wide">Graph Intelligence</span>
        </div>

        {/* Backend & latency chip */}
        <div className="flex items-center gap-1.5">
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${badgeConfig.badgeClass}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${badgeConfig.dotClass}`} />
            {badgeConfig.label}
          </span>
        </div>
      </div>

      {loading && !data ? (
        <div className="text-xs text-slate-500 py-3 text-center flex items-center justify-center gap-2">
          <span className="w-3 h-3 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
          Querying topology graph...
        </div>
      ) : (
        <>
          {/* Key Metrics Row */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            {/* Blast radius */}
            <div className="bg-slate-900/60 border border-slate-800/90 rounded-lg p-2 flex flex-col justify-between">
              <div className="text-[11px] text-slate-400 font-medium">Blast Radius</div>
              <div className="flex items-baseline gap-1.5 mt-0.5">
                <span className="text-base font-bold text-white">{blastCount}</span>
                <span className="text-[10px] text-slate-400">subscribers</span>
              </div>
              {essentialCount > 0 && (
                <div className="mt-1 text-[10px] text-amber-300 font-medium flex items-center gap-1">
                  <span>🏛️</span>
                  <span>{essentialCount} essential prioritized</span>
                </div>
              )}
            </div>

            {/* 30-Day History */}
            <div className="bg-slate-900/60 border border-slate-800/90 rounded-lg p-2 flex flex-col justify-between">
              <div className="text-[11px] text-slate-400 font-medium">30-Day History</div>
              <div className="flex items-baseline gap-1.5 mt-0.5">
                <span className="text-base font-bold text-white">{historyCount}×</span>
                <span className="text-[10px] text-slate-400">incidents ({linkId})</span>
              </div>
              <div className="mt-1 text-[10px] text-slate-400">
                {historyCount >= 3 ? '⚠️ Chronic failure component' : 'Baseline stability nominal'}
              </div>
            </div>
          </div>

          {/* Failure Path Chain */}
          {pathNodes.length > 0 && (
            <div className="bg-slate-900/40 border border-slate-800/80 rounded-lg p-2">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1.5">
                Failure Path (from Gateway)
              </div>
              <div className="flex items-center gap-1 flex-wrap text-xs">
                {pathNodes.map((node, idx) => (
                  <div key={node} className="flex items-center gap-1">
                    <span className={`px-2 py-0.5 rounded text-[11px] font-mono font-medium ${
                      idx === 0
                        ? 'bg-blue-950/80 border border-blue-700/70 text-blue-300'
                        : idx === pathNodes.length - 1
                        ? 'bg-rose-950/80 border border-rose-700/70 text-rose-300'
                        : 'bg-slate-800/80 border border-slate-700 text-slate-300'
                    }`}>
                      {node}
                    </span>
                    {idx < pathNodes.length - 1 && (
                      <span className="text-slate-500 text-xs">→</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* "Show Cypher" Expander */}
          <div className="pt-0.5">
            <button
              type="button"
              onClick={() => setShowCypher(prev => !prev)}
              className="text-xs font-medium text-cyan-400 hover:text-cyan-300 transition-colors flex items-center gap-1 select-none"
            >
              <span>{showCypher ? '▼ Hide Cypher Queries' : '▶ Show Cypher Queries'}</span>
              <span className="text-[10px] text-slate-500">
                ({isNeo4j ? `${queries.length} live` : 'parameterized Cypher'})
              </span>
            </button>

            {showCypher && (
              <div className="mt-2 space-y-2 bg-[#040914] border border-slate-800 rounded-lg p-2.5 text-xs">
                <div className="text-[10px] text-slate-400 flex items-center justify-between border-b border-slate-800 pb-1.5">
                  <span>Cypher Queries executed for this incident</span>
                  <span className="text-[10px] text-emerald-400 font-mono">
                    {isNeo4j ? 'Engine: Neo4j Aura' : 'Engine: In-Memory / Neo4j Ready'}
                  </span>
                </div>
                {queries.map((q, i) => (
                  <div key={q.name || i} className="space-y-1">
                    <div className="flex items-center justify-between text-[11px] font-semibold text-slate-300">
                      <span className="font-mono text-cyan-300">query: {q.name}</span>
                      {q.ms !== undefined && (
                        <span className="text-slate-500 text-[10px]">
                          {q.rows ?? 0} rows · {q.ms} ms
                        </span>
                      )}
                    </div>
                    {q.description && (
                      <div className="text-[10px] text-slate-400 italic">{q.description}</div>
                    )}
                    <pre className="p-2 bg-slate-950 rounded text-[11px] font-mono text-slate-300 overflow-x-auto whitespace-pre border border-slate-800/80">
                      <code>{q.cypher}</code>
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
