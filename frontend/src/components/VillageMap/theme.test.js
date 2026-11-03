import test from 'node:test';
import assert from 'node:assert/strict';
import { telemetryLabel } from './theme.js';

test('telemetryLabel: returns Simulated telemetry for simulated', () => {
  assert.equal(telemetryLabel('simulated'), 'Simulated telemetry');
});

test('telemetryLabel: returns Measured telemetry for measured', () => {
  assert.equal(telemetryLabel('measured'), 'Measured telemetry');
});

test('telemetryLabel: returns null for anything else', () => {
  assert.equal(telemetryLabel('loading'), null);
  assert.equal(telemetryLabel('unknown'), null);
  assert.equal(telemetryLabel(null), null);
  assert.equal(telemetryLabel(undefined), null);
  assert.equal(telemetryLabel(''), null);
});
