import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  RELEASE_DEPENDENCIES,
  RELEASE_STATES,
  ReleaseStateMachine,
  evaluateFailureScenario,
  seedStateMachine,
} from './release-state-machine.mjs';

assert.equal(RELEASE_STATES.length, 19);
assert.deepEqual(RELEASE_STATES, Array.from({ length: 19 }, (_, index) =>
  `R${index}_${[
    'SAFE_PRODUCTION', 'CANDIDATE_CONSTRUCTED', 'CANDIDATE_TESTED',
    'CANDIDATE_BROWSER_E2E_ACCEPTED', 'REQUIRED_CI_ACCEPTED', 'MAIN_MERGED',
    'BACKEND_CANDIDATE_DEPLOYING', 'FRONTEND_CANDIDATE_DEPLOYING',
    'BACKEND_IDENTITY_CONVERGED', 'FRONTEND_IDENTITY_CONVERGED',
    'PRODUCT_SELECTION_READY', '1321_SELECTED', '5D_SELECTED',
    'CANONICAL_REQUEST_OBSERVED', 'VERIFIED_SNAPSHOT_RECEIVED',
    'SAME_SNAPSHOT_PROJECTED_TO_UI', 'WARM_PROFILE_SEALED',
    'PUBLIC_PRODUCT_ACCEPTED', 'V13_LIVE',
  ][index]}`));
for (const [state, dependencies] of Object.entries(RELEASE_DEPENDENCIES)) {
  const stateIndex = RELEASE_STATES.indexOf(state);
  assert.ok(stateIndex >= 0);
  for (const dependency of dependencies) {
    assert.ok(RELEASE_STATES.indexOf(dependency) < stateIndex,
      `${state} must depend only on an earlier trigger`);
  }
}

const impossible = new ReleaseStateMachine();
assert.throws(() => impossible.transition('R1_CANDIDATE_CONSTRUCTED'),
  /release_state_dependency_missing/);
assert.throws(() => impossible.transition('R99_UNKNOWN'), /unknown_release_state/);
impossible.transition('R0_SAFE_PRODUCTION');
assert.throws(() => impossible.transition('R0_SAFE_PRODUCTION'), /duplicate_release_state/);

const seed = seedStateMachine();
for (const state of RELEASE_STATES.slice(10, 17)) seed.transition(state);
assert.deepEqual(seed.log.map((event) => event.state), RELEASE_STATES.slice(0, 17));

const accepted = {
  frontendIdentity: 'candidate', backendIdentity: 'candidate', oldFrontend: false,
  todayLoaded: true, selected1321: true, selected5D: true, httpStatuses: [200],
  verificationStatus: 'verified', responseSnapshotId: 'mts-a', uiSnapshotId: 'mts-a',
  serviceWorkerReady: true, indexedDbReady: true, profileValid: true,
  identityStable: true,
};
const matrix = {
  A: [{ ...accepted, defaultTodayDataGated: true }, true, 'accepted'],
  B: [{ ...accepted, oldFrontend: true }, false, 'old_frontend'],
  C: [{ ...accepted, backendIdentity: 'stale' }, false, 'backend_identity'],
  D: [{ ...accepted, frontendIdentity: 'stale' }, false, 'frontend_identity'],
  E: [accepted, true, 'accepted'],
  F: [{ ...accepted, httpStatuses: [400] }, false, 'http_not_200'],
  G: [{ ...accepted, httpStatuses: [429, 200] }, true, 'accepted'],
  H: [{ ...accepted, httpStatuses: [429, 429, 429] }, false, 'rate_limit_exhausted'],
  I: [{ ...accepted, verificationStatus: 'unverified' }, false, 'not_verified'],
  J: [{ ...accepted, uiSnapshotId: 'mts-b' }, false, 'snapshot_mismatch'],
  K: [accepted, true, 'accepted'],
  L: [{ ...accepted, serviceWorkerReady: false }, false, 'service_worker'],
  M: [{ ...accepted, indexedDbReady: false }, false, 'indexeddb'],
  N: [{ ...accepted, profileValid: false }, false, 'profile'],
  O: [{ ...accepted, frontendIdentityChanged: true }, false, 'identity_changed'],
  P: [{ ...accepted, backendIdentityChanged: true }, false, 'identity_changed'],
};
for (const [scenario, [input, pass, reason]] of Object.entries(matrix)) {
  assert.deepEqual(evaluateFailureScenario(input), { pass, reason }, scenario);
}

const selection = fs.readFileSync(
  new URL('./canonical-snapshot-selection.mjs', import.meta.url), 'utf8');
const requestRegistration = selection.indexOf('const requestPromise = page.waitForRequest');
const responseRegistration = selection.indexOf('const responsePromise = page.waitForResponse');
const select1321 = selection.indexOf('R11_1321_SELECTED');
const select5D = selection.indexOf('R12_5D_SELECTED');
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
  'selection must trigger before waits and the UI wait must follow the verified response');
assert.match(selection, /attempt <= 3/);
assert.match(selection, /observedResponse\.status\(\) !== 429/);

const acceptance = fs.readFileSync(
  new URL('./public-market-acceptance.mjs', import.meta.url), 'utf8');
const seedProbe = acceptance.slice(acceptance.indexOf("if (MODE === 'seed')"));
assert.ok(seedProbe.indexOf('selectCanonical1321FiveDay')
  < seedProbe.indexOf('probeProfileRuntime'));
assert.ok(seedProbe.indexOf('writeWarmProfileManifest')
  < seedProbe.indexOf("transition('R16_WARM_PROFILE_SEALED'"));

console.log('release-state-machine.test: ok (R0-R18 and failure matrix A-P)');
