import assert from 'node:assert/strict';
import { validateCanonicalProjectionState } from './canonical-snapshot-selection.mjs';

const snapshotId = `vs-${'a'.repeat(32)}`;
const available = {
  state: 'available',
  snapshotId,
  responseSnapshotId: snapshotId,
  snapshotState: 'CURRENT_READY',
};
const missing = {
  state: 'missing',
  snapshotId: null,
  responseSnapshotId: null,
  snapshotState: 'NO_CACHE_LOADING',
};

assert.deepEqual(validateCanonicalProjectionState({
  nodes: [available],
  expectedSnapshotId: snapshotId,
  expectedSnapshotState: 'CURRENT_READY',
  acceptedResponseSnapshotId: snapshotId,
}).pass, true, 'available canonical projection must pass');

assert.deepEqual(validateCanonicalProjectionState({
  nodes: [missing], acceptedResponseSnapshotId: null,
}).pass,
  true, 'canonical missing projection must pass without an accepted response');

assert.deepEqual(validateCanonicalProjectionState({ nodes: [] }), {
  pass: false,
  reason: 'projection_state_missing',
}, 'neither state must fail');

assert.deepEqual(validateCanonicalProjectionState({ nodes: [available, missing] }), {
  pass: false,
  reason: 'contradictory_projection_states',
}, 'contradictory states must fail');

assert.deepEqual(validateCanonicalProjectionState({
  nodes: [available],
  expectedSnapshotId: snapshotId,
  expectedSnapshotState: 'CURRENT_READY',
  acceptedResponseSnapshotId: `vs-${'b'.repeat(32)}`,
}), {
  pass: false,
  reason: 'projection_accepted_response_mismatch',
}, 'projection identity must belong to the accepted canonical response');

assert.equal(validateCanonicalProjectionState({
  nodes: [available],
  expectedSnapshotId: snapshotId,
  expectedSnapshotState: 'STALE_FALLBACK',
  acceptedResponseSnapshotId: snapshotId,
}).reason, 'projection_snapshot_state_mismatch',
'projection state must match the accepted canonical response state');

console.log('mobile-today-projection-state: PASS');
