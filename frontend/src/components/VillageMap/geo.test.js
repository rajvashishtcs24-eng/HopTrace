import test from 'node:test';
import assert from 'node:assert/strict';
import { computeBounds } from './geo.js';

test('computeBounds: returns null for non-array or empty inputs', () => {
  assert.equal(computeBounds(null), null);
  assert.equal(computeBounds(undefined), null);
  assert.equal(computeBounds([]), null);
  assert.equal(computeBounds('invalid'), null);
});

test('computeBounds: returns null if no nodes have finite lat and lon', () => {
  const nodes = [
    { id: 'n1', lat: null, lon: 80.5 },
    { id: 'n2', lat: 'invalid', lon: 80.5 },
    { id: 'n3', lat: NaN, lon: NaN },
    { id: 'n4', lat: 27.1, lon: undefined },
    null,
  ];
  assert.equal(computeBounds(nodes), null);
});

test('computeBounds: computes bounding box correctly for valid nodes', () => {
  const nodes = [
    { id: 'n1', lat: 27.20000, lon: 80.60000 },
    { id: 'n2', lat: 27.22879, lon: 80.60000 },
    { id: 'n3', lat: 27.17511, lon: 80.62534 },
    { id: 'n4', lat: null, lon: null }, // ignored
  ];
  const bounds = computeBounds(nodes);
  assert.ok(bounds);
  assert.deepEqual(bounds, [
    [27.17511, 80.60000],
    [27.22879, 80.62534],
  ]);
});

test('computeBounds: handles single valid node', () => {
  const nodes = [{ id: 'n1', lat: 27.2, lon: 80.6 }];
  const bounds = computeBounds(nodes);
  assert.deepEqual(bounds, [
    [27.2, 80.6],
    [27.2, 80.6],
  ]);
});
