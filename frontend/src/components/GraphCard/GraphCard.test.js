/**
 * Track N (Neo4j) — Unit tests for GraphCard helpers and Cypher templates
 *
 * Uses node:test + node:assert/strict
 * Run from frontend/: node --test src/components/GraphCard/GraphCard.test.js
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_CYPHER_QUERIES,
  formatGraphBackendBadge,
  countEssentialSubscribers,
  formatPathNodes,
} from './graphHelpers.js';

describe('formatGraphBackendBadge', () => {
  it('returns emerald badge for connected Neo4j', () => {
    const badge = formatGraphBackendBadge('neo4j', false);
    assert.equal(badge.label, 'via Neo4j');
    assert.ok(badge.badgeClass.includes('emerald'));
    assert.ok(badge.dotClass.includes('animate-pulse'));
  });

  it('returns amber badge for in-memory fallback', () => {
    const badge = formatGraphBackendBadge('memory', true);
    assert.equal(badge.label, 'Fallback: in-memory');
    assert.ok(badge.badgeClass.includes('amber'));
  });

  it('returns slate/cyan badge for standard in-memory mode', () => {
    const badge = formatGraphBackendBadge('memory', false);
    assert.equal(badge.label, 'In-memory graph');
    assert.ok(badge.badgeClass.includes('slate'));
  });
});

describe('countEssentialSubscribers', () => {
  it('counts essential subscribers accurately', () => {
    const subs = [
      { id: 'SUB101', name: 'Kirana Store', is_essential: false },
      { id: 'SUB102', name: 'Gram Panchayat', is_essential: true },
      { id: 'SUB103', name: 'PHC Clinic', is_essential: true },
    ];
    assert.equal(countEssentialSubscribers(subs), 2);
  });

  it('handles empty or non-array inputs gracefully', () => {
    assert.equal(countEssentialSubscribers([]), 0);
    assert.equal(countEssentialSubscribers(null), 0);
    assert.equal(countEssentialSubscribers(undefined), 0);
  });
});

describe('formatPathNodes', () => {
  it('filters and validates node IDs in path', () => {
    const nodes = ['GW1', 'R1', 'WB1', '', null, 'WB2'];
    const formatted = formatPathNodes(nodes);
    assert.deepEqual(formatted, ['GW1', 'R1', 'WB1', 'WB2']);
  });

  it('handles null or non-array inputs gracefully', () => {
    assert.deepEqual(formatPathNodes(null), []);
    assert.deepEqual(formatPathNodes(undefined), []);
  });
});

describe('DEFAULT_CYPHER_QUERIES', () => {
  it('contains blast_radius, shortest_path, and incident_history_30d', () => {
    const names = DEFAULT_CYPHER_QUERIES.map(q => q.name);
    assert.ok(names.includes('blast_radius'));
    assert.ok(names.includes('shortest_path'));
    assert.ok(names.includes('incident_history_30d'));
  });

  it('uses parameterized Cypher ($component_id, $gateway_id, $target_node_id)', () => {
    for (const q of DEFAULT_CYPHER_QUERIES) {
      assert.ok(q.cypher.includes('$'), `Query ${q.name} must be parameterized`);
    }
  });
});
