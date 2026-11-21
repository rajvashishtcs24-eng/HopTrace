/**
 * Track N (Neo4j) — Pure helper functions and query templates for GraphCard
 */

export const DEFAULT_CYPHER_QUERIES = [
  {
    name: 'blast_radius',
    cypher: `MATCH (d:Device {id: $component_id})-[:LINK*0..]->(ap:Device {type: 'access_point'})-[:SERVES]->(s:Subscriber)
RETURN s.id AS id, s.name AS name, ap.id AS access_point_id`,
    description: 'Traverses downstream topology tree from failed link to identify affected subscribers',
  },
  {
    name: 'shortest_path',
    cypher: `MATCH path = shortestPath((g:Device {id: $gateway_id})-[:LINK*..15]->(target:Device {id: $target_node_id}))
RETURN [n IN nodes(path) | n.id] AS nodes, [r IN relationships(path) | r.id] AS links`,
    description: 'Finds optimal network path from Gateway PoP to the point of failure',
  },
  {
    name: 'incident_history_30d',
    cypher: `MATCH (i:Incident)-[:AT]->(d:Device)
WHERE (d.id = $component_id OR EXISTS { MATCH (d)-[l:LINK]-(:Device) WHERE l.id = $component_id })
  AND i.started_at >= datetime() - duration({days: 30})
RETURN count(i) AS incidents_30d`,
    description: 'Aggregates chronic component failures over rolling 30-day window',
  },
];

export function formatGraphBackendBadge(backend, fallback) {
  if (backend === 'neo4j' && !fallback) {
    return {
      label: 'via Neo4j',
      badgeClass: 'bg-emerald-950/80 border-emerald-600/80 text-emerald-300',
      dotClass: 'bg-emerald-400 animate-pulse',
    };
  }
  if (fallback) {
    return {
      label: 'Fallback: in-memory',
      badgeClass: 'bg-amber-950/80 border-amber-600/80 text-amber-300',
      dotClass: 'bg-amber-400',
    };
  }
  return {
    label: 'In-memory graph',
    badgeClass: 'bg-slate-900 border-slate-700 text-slate-300',
    dotClass: 'bg-cyan-400',
  };
}

export function countEssentialSubscribers(subscribers = []) {
  if (!Array.isArray(subscribers)) return 0;
  return subscribers.filter(s => s && s.is_essential).length;
}

export function formatPathNodes(nodes = []) {
  if (!Array.isArray(nodes)) return [];
  return nodes.filter(n => typeof n === 'string' && n.trim() !== '');
}
