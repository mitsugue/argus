export const RELEASE_STATES = Object.freeze([
  'R0_SAFE_PRODUCTION',
  'R1_CANDIDATE_CONSTRUCTED',
  'R2_CANDIDATE_TESTED',
  'R3_CANDIDATE_BROWSER_E2E_ACCEPTED',
  'R4_REQUIRED_CI_ACCEPTED',
  'R5_MAIN_MERGED',
  'R6_BACKEND_CANDIDATE_DEPLOYING',
  'R7_FRONTEND_CANDIDATE_DEPLOYING',
  'R8_BACKEND_IDENTITY_CONVERGED',
  'R9_FRONTEND_IDENTITY_CONVERGED',
  'R10_PRODUCT_SELECTION_READY',
  'R11_1321_SELECTED',
  'R12_5D_SELECTED',
  'R13_CANONICAL_REQUEST_OBSERVED',
  'R14_VERIFIED_SNAPSHOT_RECEIVED',
  'R15_SAME_SNAPSHOT_PROJECTED_TO_UI',
  'R16_WARM_PROFILE_SEALED',
  'R17_PUBLIC_PRODUCT_ACCEPTED',
  'R18_V13_LIVE',
]);

export const RELEASE_DEPENDENCIES = Object.freeze({
  R0_SAFE_PRODUCTION: [],
  R1_CANDIDATE_CONSTRUCTED: ['R0_SAFE_PRODUCTION'],
  R2_CANDIDATE_TESTED: ['R1_CANDIDATE_CONSTRUCTED'],
  R3_CANDIDATE_BROWSER_E2E_ACCEPTED: ['R2_CANDIDATE_TESTED'],
  R4_REQUIRED_CI_ACCEPTED: ['R3_CANDIDATE_BROWSER_E2E_ACCEPTED'],
  R5_MAIN_MERGED: ['R4_REQUIRED_CI_ACCEPTED'],
  R6_BACKEND_CANDIDATE_DEPLOYING: ['R5_MAIN_MERGED'],
  R7_FRONTEND_CANDIDATE_DEPLOYING: ['R5_MAIN_MERGED'],
  R8_BACKEND_IDENTITY_CONVERGED: ['R6_BACKEND_CANDIDATE_DEPLOYING'],
  R9_FRONTEND_IDENTITY_CONVERGED: ['R7_FRONTEND_CANDIDATE_DEPLOYING'],
  R10_PRODUCT_SELECTION_READY: [
    'R8_BACKEND_IDENTITY_CONVERGED', 'R9_FRONTEND_IDENTITY_CONVERGED',
  ],
  R11_1321_SELECTED: ['R10_PRODUCT_SELECTION_READY'],
  R12_5D_SELECTED: ['R11_1321_SELECTED'],
  R13_CANONICAL_REQUEST_OBSERVED: ['R12_5D_SELECTED'],
  R14_VERIFIED_SNAPSHOT_RECEIVED: ['R13_CANONICAL_REQUEST_OBSERVED'],
  R15_SAME_SNAPSHOT_PROJECTED_TO_UI: ['R14_VERIFIED_SNAPSHOT_RECEIVED'],
  R16_WARM_PROFILE_SEALED: ['R15_SAME_SNAPSHOT_PROJECTED_TO_UI'],
  R17_PUBLIC_PRODUCT_ACCEPTED: ['R16_WARM_PROFILE_SEALED'],
  R18_V13_LIVE: ['R17_PUBLIC_PRODUCT_ACCEPTED'],
});

const stateSet = new Set(RELEASE_STATES);

export class ReleaseStateMachine {
  constructor({ assumed = [], onTransition = () => {} } = {}) {
    this.reached = new Set();
    this.log = [];
    this.onTransition = onTransition;
    for (const state of assumed) this.transition(state, { assumed: true });
  }

  transition(state, detail = null) {
    if (!stateSet.has(state)) throw new Error(`unknown_release_state:${state}`);
    if (this.reached.has(state)) throw new Error(`duplicate_release_state:${state}`);
    const missing = RELEASE_DEPENDENCIES[state]
      .filter((dependency) => !this.reached.has(dependency));
    if (missing.length) {
      throw new Error(`release_state_dependency_missing:${state}:${missing.join(',')}`);
    }
    const event = { index: this.log.length + 1, state, detail };
    this.reached.add(state);
    this.log.push(event);
    this.onTransition(event);
    return event;
  }
}

export function seedStateMachine(onTransition = () => {}) {
  return new ReleaseStateMachine({
    assumed: RELEASE_STATES.slice(0, 10),
    onTransition,
  });
}

export function evaluateFailureScenario(input) {
  const statuses = input.httpStatuses ?? [200];
  if (input.frontendIdentity !== 'candidate') return { pass: false, reason: 'frontend_identity' };
  if (input.backendIdentity !== 'candidate') return { pass: false, reason: 'backend_identity' };
  if (input.oldFrontend === true) return { pass: false, reason: 'old_frontend' };
  if (!input.todayLoaded) return { pass: false, reason: 'today_not_loaded' };
  if (!input.selected1321) return { pass: false, reason: '1321_not_selected' };
  if (!input.selected5D) return { pass: false, reason: '5d_not_selected' };
  if (statuses.some((status) => status === 429)
      && statuses.filter((status) => status === 429).length > 2) {
    return { pass: false, reason: 'rate_limit_exhausted' };
  }
  if (!statuses.includes(200)) return { pass: false, reason: 'http_not_200' };
  if (input.verificationStatus !== 'verified') return { pass: false, reason: 'not_verified' };
  if (!input.responseSnapshotId) return { pass: false, reason: 'response_snapshot_missing' };
  if (input.responseSnapshotId !== input.uiSnapshotId) return { pass: false, reason: 'snapshot_mismatch' };
  if (!input.serviceWorkerReady) return { pass: false, reason: 'service_worker' };
  if (!input.indexedDbReady) return { pass: false, reason: 'indexeddb' };
  if (!input.profileValid) return { pass: false, reason: 'profile' };
  if (!input.identityStable || input.frontendIdentityChanged
      || input.backendIdentityChanged) {
    return { pass: false, reason: 'identity_changed' };
  }
  return { pass: true, reason: 'accepted' };
}
