import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  RELEASE_DEPENDENCIES,
  RELEASE_STATES,
  ReleaseStateMachine,
  evaluateBusinessSnapshotSet,
  evaluateFailureScenario,
  evaluateInfrastructureReadiness,
  finalizePublicAcceptance,
  loadSnapshotContract,
  seedStateMachine,
  snapshotIdentity,
  triggerBusinessSnapshots,
  validateSnapshotContract,
} from './release-state-machine.mjs';

const contract = validateSnapshotContract(loadSnapshotContract(
  new URL('../../release/v13-snapshot-readiness-contract.json', import.meta.url),
));
assert.equal(contract.snapshotExpected, 12);
assert.equal(new Set(contract.snapshots.map((row) => row.identity)).size, 12);
assert.ok(contract.snapshots.every((row) => row.requiredness === 'SEED_REQUIRED'));

assert.equal(RELEASE_STATES.length, 21);
assert.deepEqual(RELEASE_STATES, Array.from({ length: 21 }, (_, index) =>
  `R${index}_${[
    'SAFE_PRODUCTION', 'CANDIDATE_CONSTRUCTED', 'CANDIDATE_TESTED',
    'CANDIDATE_BROWSER_E2E_ACCEPTED', 'REQUIRED_CI_ACCEPTED', 'MAIN_MERGED',
    'BACKEND_DEPLOYING', 'BACKEND_INFRA_READY', 'FRONTEND_DEPLOYING',
    'FRONTEND_IDENTITY_CONVERGED', 'BACKEND_IDENTITY_CONVERGED',
    'PRODUCT_SELECTION_READY', '1321_SELECTED', '5D_SELECTED',
    'CANONICAL_REQUEST_OBSERVED', 'VERIFIED_SNAPSHOT_RECEIVED',
    'UI_SNAPSHOT_ID_MATCHED', 'WARM_PROFILE_SEALED',
    'BUSINESS_SNAPSHOT_SET_ACCEPTED', 'PUBLIC_PRODUCT_ACCEPTED', 'V13_LIVE',
  ][index]}`));
for (const [state, dependencies] of Object.entries(RELEASE_DEPENDENCIES)) {
  const stateIndex = RELEASE_STATES.indexOf(state);
  assert.ok(stateIndex >= 0);
  for (const dependency of dependencies) {
    assert.ok(RELEASE_STATES.indexOf(dependency) < stateIndex,
      `${state} must depend only on an earlier producer state`);
  }
}

const impossible = new ReleaseStateMachine();
assert.throws(() => impossible.transition('R1_CANDIDATE_CONSTRUCTED'),
  /release_state_dependency_missing/);
assert.throws(() => impossible.transition('R99_UNKNOWN'), /unknown_release_state/);
impossible.transition('R0_SAFE_PRODUCTION');
assert.throws(() => impossible.transition('R0_SAFE_PRODUCTION'), /duplicate_release_state/);

const complete = new ReleaseStateMachine();
for (const state of RELEASE_STATES) complete.transition(state);
assert.deepEqual(complete.log.map((event) => event.state), RELEASE_STATES);
assert.equal(complete.rollback('R19_PUBLIC_PRODUCT_ACCEPTED').state,
  'ROLLBACK_TO_R0_SAFE_PRODUCTION');

const seed = seedStateMachine();
for (const state of RELEASE_STATES.slice(11, 18)) seed.transition(state);
assert.deepEqual(seed.log.map((event) => event.state), RELEASE_STATES.slice(0, 18));

const buildSha = 'a'.repeat(40);
const triggerId = 'release-simulation-1';
const triggeredAt = '2026-08-18T00:00:00.000Z';
const generatedAt = '2026-08-18T00:00:01.000Z';
const observed = contract.snapshots.map((row, index) => ({
  schemaVersion: 'argus-verified-view-snapshot-v1',
  snapshotId: `vs-${String(index).padStart(32, '0')}`,
  kind: row.kind,
  market: row.market,
  instrument: row.instrument,
  horizon: row.horizon,
  datasetHash: `dataset-${index}`,
  payloadHash: `payload-${index}`,
  methodVersion: 'verified-chart-view-v1:test',
  asOf: triggeredAt,
  generatedAt,
  verifiedAt: generatedAt,
  quality: 'live',
  sourceStatus: { chart: 'complete' },
  verificationStatus: 'verified',
  releaseBinding: {
    expectedBuildSha: buildSha,
    producerTriggerId: triggerId,
    triggeredAt,
  },
  payload: { automaticAiCalls: 0 },
}));
assert.deepEqual(evaluateInfrastructureReadiness({
  backendHealth: { status: 'ok', buildSha },
  backendReady: { ready: true, buildSha },
  expectedBuildSha: buildSha,
  processStable: true,
  crashLoop: false,
  oomKilled: false,
  storageValid: true,
  restoreOutcome: 'test_mode',
  infraSnapshots: [],
}, contract), { pass: true, reason: 'accepted', expectedSet: [], observedSet: [] });
const exact = evaluateBusinessSnapshotSet({
  contract, observed, expectedBuildSha: buildSha, producerTriggerId: triggerId,
  now: Date.parse(generatedAt) + 1000,
});
assert.equal(exact.pass, true);
assert.deepEqual(exact.expectedSet, exact.observedSet);
assert.equal(evaluateBusinessSnapshotSet({
  contract, observed: [...observed, observed[0]], expectedBuildSha: buildSha,
  producerTriggerId: triggerId, now: Date.parse(generatedAt) + 1000,
}).reason, 'duplicate_snapshot');
assert.equal(evaluateBusinessSnapshotSet({
  contract, observed: observed.slice(1), expectedBuildSha: buildSha,
  producerTriggerId: triggerId, now: Date.parse(generatedAt) + 1000,
}).reason, 'snapshot_set_mismatch');
const wrongBuild = structuredClone(observed);
wrongBuild[0].releaseBinding.expectedBuildSha = 'b'.repeat(40);
assert.match(evaluateBusinessSnapshotSet({
  contract, observed: wrongBuild, expectedBuildSha: buildSha,
  producerTriggerId: triggerId, now: Date.parse(generatedAt) + 1000,
}).reason, /^wrong_build:/);
assert.equal(snapshotIdentity(observed[0]), contract.snapshots[0].identity);
await assert.rejects(triggerBusinessSnapshots({
  baseUrl: 'https://example.invalid', adminToken: 'redacted', contract,
  expectedBuildSha: buildSha, producerTriggerId: triggerId,
  fetchImpl: async () => new Response(JSON.stringify({ status: 'duplicate' }),
    { status: 409, headers: { 'Content-Type': 'application/json' } }),
}), /business_snapshot_trigger_unacknowledged:http_409:duplicate/);
const finalized = finalizePublicAcceptance({
  businessArtifact: { status: 'pass', expectedSet: exact.expectedSet,
    observedSet: exact.observedSet },
  publicArtifact: { verdict: 'PASS', frontendSha: buildSha },
  mobileArtifact: { verdict: 'PASS', frontendSha: buildSha },
  expectedFrontendSha: buildSha,
});
assert.deepEqual(finalized.releaseStateLog.slice(-2).map((row) => row.state), [
  'R19_PUBLIC_PRODUCT_ACCEPTED', 'R20_V13_LIVE',
]);
assert.throws(() => finalizePublicAcceptance({
  businessArtifact: { status: 'pass', expectedSet: exact.expectedSet,
    observedSet: exact.observedSet.slice(1) },
  publicArtifact: { verdict: 'PASS', frontendSha: buildSha },
  mobileArtifact: { verdict: 'PASS', frontendSha: buildSha },
  expectedFrontendSha: buildSha,
}), /finalize_business_artifact_invalid/);

const accepted = {
  initialSnapshotReady: 0,
  infrastructureHealthy: true,
  frontendIdentity: 'candidate', backendIdentity: 'candidate', oldFrontend: false,
  frontendDeployedBeforeSeed: true,
  todayLoaded: true, selected1321: true, selected5D: true, httpStatuses: [200],
  verificationStatus: 'verified', responseSnapshotId: 'mts-a', uiSnapshotId: 'mts-a',
  serviceWorkerReady: true, serviceWorkerStale: false,
  indexedDbInitiallyEmpty: true, indexedDbReady: true, profileValid: true,
  identityStable: true, externalDataGatedAbsent: true,
};
const matrix = {
  A: [accepted, true, 'accepted'],
  B: [{ ...accepted, infrastructureHealthy: true }, true, 'accepted'],
  C: [{ ...accepted, infrastructureHealthy: false }, false, 'infrastructure'],
  D: [{ ...accepted, oldFrontend: true }, false, 'old_frontend'],
  E: [{ ...accepted, frontendIdentity: 'stale' }, false, 'frontend_identity'],
  F: [{ ...accepted, backendIdentity: 'stale' }, false, 'backend_identity'],
  G: [{ ...accepted, frontendDeployedBeforeSeed: true }, true, 'accepted'],
  H: [{ ...accepted, httpStatuses: [400] }, false, 'http_not_200'],
  I: [{ ...accepted, httpStatuses: [429, 200] }, true, 'accepted'],
  J: [{ ...accepted, httpStatuses: [429, 429, 429] }, false, 'rate_limit_exhausted'],
  K: [{ ...accepted, verificationStatus: 'unverified' }, false, 'not_verified'],
  L: [{ ...accepted, uiSnapshotId: 'mts-b' }, false, 'snapshot_mismatch'],
  M: [{ ...accepted, serviceWorkerStale: true }, false, 'service_worker'],
  N: [{ ...accepted, indexedDbInitiallyEmpty: true }, true, 'accepted'],
  O: [{ ...accepted, profileValid: false }, false, 'profile'],
  P: [{ ...accepted, wrongBuildSnapshot: true }, false, 'wrong_build_snapshot'],
  Q: [{ ...accepted, duplicateSnapshot: true }, false, 'duplicate_snapshot'],
  R: [{ ...accepted, missingSeedRequired: true }, false, 'missing_seed_required'],
  S: [{ ...accepted, externalDataGatedAbsent: true }, true, 'accepted'],
  T: [{ ...accepted, frontendIdentityChanged: true }, false, 'identity_changed'],
};
for (const [scenario, [input, pass, reason]] of Object.entries(matrix)) {
  assert.deepEqual(evaluateFailureScenario(input), { pass, reason }, scenario);
}

const selection = fs.readFileSync(
  new URL('./canonical-snapshot-selection.mjs', import.meta.url), 'utf8');
const requestRegistration = selection.indexOf('const requestPromise = page.waitForRequest');
const responseRegistration = selection.indexOf('const responsePromise = page.waitForResponse');
const select1321 = selection.indexOf('R12_1321_SELECTED');
const select5D = selection.indexOf('R13_5D_SELECTED');
const revalidationTrigger = selection.indexOf(
  "await page.reload({ waitUntil: 'domcontentloaded', timeout })",
);
const awaitRequestAndResponse = selection.indexOf(
  'return Promise.all([requestPromise, responsePromise])',
);
const retryLoop = selection.indexOf('for (let attempt = 1; attempt <= 3; attempt += 1)');
const awaitUi = selection.indexOf('await page.waitForFunction(({ selector, snapshotId })');
assert.ok(requestRegistration >= 0 && responseRegistration > requestRegistration);
assert.ok(select1321 >= 0 && select5D > select1321);
assert.ok(revalidationTrigger > responseRegistration
  && awaitRequestAndResponse > revalidationTrigger
  && retryLoop > select5D && awaitUi > retryLoop,
  'selection must trigger before waits and UI equality must follow the verified response');
assert.match(selection, /attempt <= 3/);
assert.match(selection, /observedResponse\.status\(\) !== 429/);

const acceptance = fs.readFileSync(
  new URL('./public-market-acceptance.mjs', import.meta.url), 'utf8');
const seedProbe = acceptance.slice(acceptance.indexOf("if (MODE === 'seed')"));
assert.ok(seedProbe.indexOf('selectCanonical1321FiveDay')
  < seedProbe.indexOf('probeProfileRuntime'));
assert.ok(seedProbe.indexOf('writeWarmProfileManifest')
  < seedProbe.indexOf("transition('R17_WARM_PROFILE_SEALED'"));

console.log('release-state-machine.test: ok (R0-R20, exact 12-set, failure matrix A-T)');
