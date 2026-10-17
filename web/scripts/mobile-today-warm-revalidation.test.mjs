import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  validateCanonicalWarmRevalidationState,
  validateCanonicalWarmRevalidationTransition,
} from './canonical-snapshot-selection.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const cached = `vs-${'a'.repeat(32)}`;
const newer = `vs-${'b'.repeat(32)}`;
const node = ({
  state = 'available', snapshotId = cached, responseSnapshotId = null,
  snapshotState = 'CACHE_READY_REVALIDATING', revalidationState = 'background',
} = {}) => ({
  state, snapshotId, responseSnapshotId, snapshotState, revalidationState,
});

const warm = node();
assert.equal(validateCanonicalWarmRevalidationState({
  nodes: [warm], expectedRevalidationState: 'background',
  cachedSnapshotId: cached, acceptedResponseSnapshotId: null,
}).pass, true, '1 warm cached snapshot is immediately valid');

assert.equal(validateCanonicalWarmRevalidationTransition({
  cachedSnapshotId: cached,
  revalidatingNodes: [warm],
  finalNodes: [node({
    snapshotState: 'CURRENT_READY', revalidationState: 'settled',
    responseSnapshotId: cached,
  })],
  acceptedResponseSnapshotId: cached,
}).pass, true, '2 background revalidation is a coherent semantic state');

assert.equal(validateCanonicalWarmRevalidationTransition({
  cachedSnapshotId: cached,
  revalidatingNodes: [warm],
  finalNodes: [node({
    snapshotState: 'CURRENT_READY', revalidationState: 'settled',
    responseSnapshotId: cached,
  })],
  acceptedResponseSnapshotId: cached,
}).outcome, 'same-snapshot', '3 same verified snapshot settles without replacement');

assert.deepEqual(validateCanonicalWarmRevalidationTransition({
  cachedSnapshotId: cached,
  revalidatingNodes: [warm],
  finalNodes: [node({
    snapshotId: newer, responseSnapshotId: newer,
    snapshotState: 'CURRENT_READY', revalidationState: 'settled',
  })],
  acceptedResponseSnapshotId: newer,
}).outcome, 'newer-snapshot', '4 newer verified snapshot transitions atomically');

assert.equal(validateCanonicalWarmRevalidationTransition({
  cachedSnapshotId: cached,
  revalidatingNodes: [warm],
  finalNodes: [node({
    snapshotState: 'ERROR_WITH_CACHE', revalidationState: 'cached-safe',
  })],
  failed: true,
}).pass, true, '5 failed revalidation retains the valid warm snapshot');

assert.equal(validateCanonicalWarmRevalidationState({
  nodes: [node({
    state: 'missing', snapshotId: null, responseSnapshotId: null,
    snapshotState: 'NO_CACHE_LOADING', revalidationState: 'cold-loading',
  })],
  expectedRevalidationState: 'cold-loading', acceptedResponseSnapshotId: null,
}).pass, true, '6 no valid cache uses the cold-loading contract');

assert.equal(validateCanonicalWarmRevalidationState({
  nodes: [node({
    snapshotId: newer, responseSnapshotId: cached,
    snapshotState: 'CURRENT_READY', revalidationState: 'settled',
  })],
  expectedRevalidationState: 'settled', acceptedResponseSnapshotId: cached,
}).reason, 'mixed_response_ui_snapshot_identity',
'7 mixed response and UI snapshot identity fails closed');

assert.equal(validateCanonicalWarmRevalidationState({
  nodes: [warm, node({
    state: 'missing', snapshotId: null, snapshotState: 'NO_CACHE_LOADING',
    revalidationState: 'cold-loading',
  })],
  expectedRevalidationState: 'background', cachedSnapshotId: cached,
}).reason, 'contradictory_warm_states',
'8 contradictory warm/loading states fail closed');

const acceptance = fs.readFileSync(path.join(here, 'mobile-today-acceptance.mjs'), 'utf8');
const warmBlock = acceptance.slice(
  acceptance.indexOf('// Warm cache is the immediate visible authority'),
  acceptance.indexOf('const before304'),
);
assert.ok(warmBlock.includes('warmResponseRelease'),
  '9 warm response uses an explicit causal release gate');
assert.doesNotMatch(warmBlock, /waitForTimeout|warmLoader|warmSkeleton|setTimeout\s*\([^)]*6_000/s,
  '9 arbitrary warm sleeps and visual-loader authority are forbidden');

console.log('mobile-today-warm-revalidation: PASS');
