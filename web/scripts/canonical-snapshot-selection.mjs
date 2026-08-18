import { seedStateMachine } from './release-state-machine.mjs';

export const CANONICAL_SNAPSHOT_SELECTOR =
  '[data-argus-contract="canonical-market-snapshot-v1"]'
  + '[data-canonical-verification="verified"]'
  + '[data-canonical-snapshot-id]';

export const CANONICAL_PROJECTION_STATE_SELECTOR =
  '[data-argus-contract="today-projection-state-v1"]';

const canonicalSnapshotId = (value) =>
  typeof value === 'string' && /^vs-[0-9a-f]{32}$/.test(value);

export function validateCanonicalProjectionState({
  nodes,
  expectedSnapshotId = null,
  expectedSnapshotState = null,
  acceptedResponseSnapshotId = undefined,
}) {
  if (!Array.isArray(nodes) || nodes.length !== 1) {
    return {
      pass: false,
      reason: Array.isArray(nodes) && nodes.length > 1
        ? 'contradictory_projection_states' : 'projection_state_missing',
    };
  }
  const node = nodes[0];
  if (!node || !['available', 'missing'].includes(node.state)
      || typeof node.snapshotState !== 'string' || !node.snapshotState) {
    return { pass: false, reason: 'invalid_projection_state_contract' };
  }
  const snapshotId = node.snapshotId || null;
  const responseSnapshotId = node.responseSnapshotId || null;
  if (expectedSnapshotId != null) {
    if (!canonicalSnapshotId(expectedSnapshotId)
        || snapshotId !== expectedSnapshotId) {
      return { pass: false, reason: 'projection_snapshot_identity_mismatch' };
    }
  } else if (snapshotId != null || responseSnapshotId != null) {
    return { pass: false, reason: 'projection_snapshot_without_accepted_response' };
  }
  if (responseSnapshotId != null && responseSnapshotId !== expectedSnapshotId) {
    return { pass: false, reason: 'projection_response_identity_mismatch' };
  }
  if (acceptedResponseSnapshotId !== undefined
      && responseSnapshotId !== acceptedResponseSnapshotId) {
    return { pass: false, reason: 'projection_accepted_response_mismatch' };
  }
  if (expectedSnapshotState != null && node.snapshotState !== expectedSnapshotState) {
    return { pass: false, reason: 'projection_snapshot_state_mismatch' };
  }
  if (node.state === 'available' && !canonicalSnapshotId(snapshotId)) {
    return { pass: false, reason: 'available_projection_without_snapshot' };
  }
  return {
    pass: true,
    reason: 'ok',
    state: node.state,
    snapshotId,
    responseSnapshotId,
    snapshotState: node.snapshotState,
  };
}

export async function readCanonicalProjectionState(page, {
  expectedSnapshotId = null,
  expectedSnapshotState = null,
  acceptedResponseSnapshotId = undefined,
} = {}) {
  const nodes = await page.locator(CANONICAL_PROJECTION_STATE_SELECTOR)
    .evaluateAll((elements) => elements.map((element) => ({
      state: element.getAttribute('data-projection-state'),
      snapshotId: element.getAttribute('data-projection-snapshot-id'),
      responseSnapshotId: element.getAttribute('data-projection-response-snapshot-id'),
      snapshotState: element.getAttribute('data-projection-snapshot-state'),
      revalidationState: element.getAttribute('data-projection-revalidation-state'),
    })));
  return validateCanonicalProjectionState({
    nodes, expectedSnapshotId, expectedSnapshotState, acceptedResponseSnapshotId,
  });
}

export function validateCanonicalWarmRevalidationState({
  nodes,
  expectedRevalidationState,
  cachedSnapshotId = null,
  acceptedResponseSnapshotId = undefined,
}) {
  if (!Array.isArray(nodes) || nodes.length !== 1) {
    return {
      pass: false,
      reason: Array.isArray(nodes) && nodes.length > 1
        ? 'contradictory_warm_states' : 'warm_state_missing',
    };
  }
  const node = nodes[0];
  const allowed = {
    background: { projection: 'available', snapshots: ['CACHE_READY_REVALIDATING'] },
    settled: { projection: 'available', snapshots: ['CURRENT_READY'] },
    'cached-safe': {
      projection: 'available', snapshots: ['ERROR_WITH_CACHE', 'STALE_FALLBACK'],
    },
    'cold-loading': { projection: 'missing', snapshots: ['NO_CACHE_LOADING'] },
    unavailable: { projection: 'missing', snapshots: ['ERROR_WITHOUT_CACHE'] },
  };
  const rule = allowed[node?.revalidationState];
  if (!rule || node.revalidationState !== expectedRevalidationState
      || node.state !== rule.projection
      || !rule.snapshots.includes(node.snapshotState)) {
    return { pass: false, reason: 'warm_state_contract_mismatch' };
  }
  const snapshotId = node.snapshotId || null;
  const responseSnapshotId = node.responseSnapshotId || null;
  if (responseSnapshotId != null && responseSnapshotId !== snapshotId) {
    return { pass: false, reason: 'mixed_response_ui_snapshot_identity' };
  }
  if (node.revalidationState === 'cold-loading'
      || node.revalidationState === 'unavailable') {
    if (snapshotId != null || responseSnapshotId != null) {
      return { pass: false, reason: 'no_cache_state_with_snapshot' };
    }
  } else if (!canonicalSnapshotId(snapshotId)) {
    return { pass: false, reason: 'warm_state_without_canonical_snapshot' };
  }
  if (node.revalidationState === 'background' && responseSnapshotId != null) {
    return { pass: false, reason: 'background_state_exposes_pending_response' };
  }
  if (cachedSnapshotId != null
      && ['background', 'cached-safe'].includes(node.revalidationState)
      && snapshotId !== cachedSnapshotId) {
    return { pass: false, reason: 'warm_cache_identity_regressed' };
  }
  if (acceptedResponseSnapshotId !== undefined) {
    if (acceptedResponseSnapshotId == null) {
      if (responseSnapshotId != null) {
        return { pass: false, reason: 'unexpected_warm_response_identity' };
      }
    } else if (!canonicalSnapshotId(acceptedResponseSnapshotId)
        || snapshotId !== acceptedResponseSnapshotId
        || responseSnapshotId !== acceptedResponseSnapshotId) {
      return { pass: false, reason: 'warm_response_ui_identity_mismatch' };
    }
  }
  return {
    pass: true,
    reason: 'ok',
    state: node.revalidationState,
    snapshotId,
    responseSnapshotId,
    snapshotState: node.snapshotState,
  };
}

export function validateCanonicalWarmRevalidationTransition({
  cachedSnapshotId,
  revalidatingNodes,
  finalNodes,
  acceptedResponseSnapshotId = undefined,
  failed = false,
}) {
  if (!canonicalSnapshotId(cachedSnapshotId)) {
    return { pass: false, reason: 'invalid_warm_cache_identity' };
  }
  const revalidating = validateCanonicalWarmRevalidationState({
    nodes: revalidatingNodes,
    expectedRevalidationState: 'background',
    cachedSnapshotId,
    acceptedResponseSnapshotId: null,
  });
  if (!revalidating.pass) return revalidating;
  const final = validateCanonicalWarmRevalidationState({
    nodes: finalNodes,
    expectedRevalidationState: failed ? 'cached-safe' : 'settled',
    cachedSnapshotId,
    acceptedResponseSnapshotId: failed ? null : acceptedResponseSnapshotId,
  });
  if (!final.pass) return final;
  if (failed && final.snapshotId !== cachedSnapshotId) {
    return { pass: false, reason: 'failed_revalidation_lost_cache' };
  }
  return {
    pass: true,
    reason: 'ok',
    cachedSnapshotId,
    finalSnapshotId: final.snapshotId,
    acceptedResponseSnapshotId: acceptedResponseSnapshotId ?? null,
    outcome: failed ? 'cached-safe' : final.snapshotId === cachedSnapshotId
      ? 'same-snapshot' : 'newer-snapshot',
  };
}

export async function readCanonicalWarmRevalidationState(page, options) {
  const nodes = await page.locator(CANONICAL_PROJECTION_STATE_SELECTOR)
    .evaluateAll((elements) => elements.map((element) => ({
      state: element.getAttribute('data-projection-state'),
      snapshotId: element.getAttribute('data-projection-snapshot-id'),
      responseSnapshotId: element.getAttribute('data-projection-response-snapshot-id'),
      snapshotState: element.getAttribute('data-projection-snapshot-state'),
      revalidationState: element.getAttribute('data-projection-revalidation-state'),
    })));
  return validateCanonicalWarmRevalidationState({ nodes, ...options });
}

// This consumer deadline is intentionally longer than the product's 75s
// verified-response producer deadline. A constrained CI/browser may receive
// HTTP 200 headers before the multi-megabyte body has streamed and passed the
// canonical verifier; the UI contract is the result, not the header event.
export const CANONICAL_RESULT_TIMEOUT_MS = 90_000;

const chartRequestMatches = (request) => {
  const url = new URL(request.url());
  return url.pathname === '/api/argus/chart-intelligence'
    && url.searchParams.get('scope') === 'market'
    && url.searchParams.get('symbol') === '1321'
    && url.searchParams.get('horizon') === '5D'
    && url.searchParams.get('snapshot') === 'verified';
};

const retryDelayMs = (response) => {
  const raw = response.headers()['retry-after'];
  const seconds = Number(raw);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.min(30_000, Math.max(1_000, seconds * 1_000));
  }
  const absolute = Date.parse(raw ?? '');
  if (Number.isFinite(absolute)) {
    return Math.min(30_000, Math.max(1_000, absolute - Date.now()));
  }
  return 30_000;
};

const CANONICAL_RESPONSE_SELECTOR =
  '[data-argus-contract="canonical-market-snapshot-v1"]'
  + '[data-canonical-response-verification="verified"]'
  + '[data-canonical-response-snapshot-id]';

async function readCanonicalResponseBody(page, timeout) {
  // The app, not Playwright/CDP, parses and verifies the actual HTTP 200 body.
  // The production contract exposes only its content-addressed scalar ID.
  // Always use this path so candidate, shadow, and production exercise one
  // identical algorithm even when a Service Worker retains response bytes.
  await page.waitForFunction(({ selector }) => {
    const contract = document.querySelector(selector);
    return /^vs-[0-9a-f]{32}$/.test(
      contract?.getAttribute('data-canonical-response-snapshot-id') ?? '');
  }, { selector: CANONICAL_RESPONSE_SELECTOR }, { timeout });
  const snapshotId = await page.locator(CANONICAL_RESPONSE_SELECTOR)
    .getAttribute('data-canonical-response-snapshot-id');
  if (!snapshotId) throw new Error('canonical_1321_5d_response_body_missing');
  return {
    body: {
      payload: { automaticAiCalls: 0 },
      snapshotId,
      verificationStatus: 'verified',
    },
    source: 'product_verified_response_contract',
  };
}

async function triggerCanonicalRevalidation(page, timeout) {
  const requestPromise = page.waitForRequest(chartRequestMatches, { timeout });
  const responsePromise = page.waitForResponse((response) =>
    chartRequestMatches(response.request()), { timeout });
  await page.reload({ waitUntil: 'domcontentloaded', timeout });
  return Promise.all([requestPromise, responsePromise]);
}

export async function openCanonicalEvidence(page, timeout = 30_000) {
  const disclosure = page.locator('details.at-evidence');
  await disclosure.waitFor({ state: 'visible', timeout });
  if (!await disclosure.evaluate((element) => element.open)) {
    await page.getByText('根拠・市場データ・システム情報', { exact: true }).click();
  }
  await page.waitForFunction(() =>
    document.querySelector('details.at-evidence')?.open === true,
  null, { timeout });
}

async function activate(locator) {
  // State changes, not layout animation stability, are the release evidence.
  // Dispatch the real DOM click synchronously and verify aria-pressed below.
  await locator.waitFor({ state: 'attached' });
  await locator.evaluate((element) => element.click());
}

export async function selectCanonical1321FiveDay(page, {
  expectedSnapshotId = null,
  timeout = CANONICAL_RESULT_TIMEOUT_MS,
  onTransition = () => {},
} = {}) {
  const machine = seedStateMachine(onTransition);
  await openCanonicalEvidence(page, timeout);
  machine.transition('R11_PRODUCT_SELECTION_READY');

  // Make both canonical controls real state transitions. A reopened profile
  // can already contain 1321/5D; merely clicking an already-selected button
  // would create no request and would reintroduce a wait-before-trigger lock.
  const canonicalInstrument = page.locator(
    '[data-argus-control="market-instrument"][data-instrument="1321"]',
  );
  const canonicalHorizon = page.locator(
    '[data-argus-control="canonical-horizon"][data-horizon="5D"]',
  );
  if (await canonicalInstrument.getAttribute('aria-pressed') === 'true') {
    const stagingInstrument = page.locator(
      '[data-argus-control="market-instrument"][data-instrument="1306"]',
    );
    await activate(stagingInstrument);
    await page.waitForFunction(() => document.querySelector(
      '[data-argus-control="market-instrument"][data-instrument="1306"]',
    )?.getAttribute('aria-pressed') === 'true', null, { timeout });
  }
  if (await canonicalHorizon.getAttribute('aria-pressed') === 'true') {
    const stagingHorizon = page.locator(
      '[data-argus-control="canonical-horizon"][data-horizon="1D"]',
    );
    await activate(stagingHorizon);
    await page.waitForFunction(() => document.querySelector(
      '[data-argus-control="canonical-horizon"][data-horizon="1D"]',
    )?.getAttribute('aria-pressed') === 'true', null, { timeout });
  }

  const marketGroup = page.getByRole('group', { name: '表示市場' });
  const jpMarket = marketGroup.getByRole('button', { name: 'JP', exact: true });
  if (await jpMarket.getAttribute('aria-pressed') !== 'true') await activate(jpMarket);
  await activate(canonicalInstrument);
  await page.waitForFunction(() => document.querySelector(
    '[data-argus-control="market-instrument"][data-instrument="1321"]',
  )?.getAttribute('aria-pressed') === 'true', null, { timeout });
  machine.transition('R12_1321_SELECTED');
  await activate(canonicalHorizon);
  await page.waitForFunction(() => document.querySelector(
    '[data-argus-control="canonical-horizon"][data-horizon="5D"]',
  )?.getAttribute('aria-pressed') === 'true', null, { timeout });
  machine.transition('R13_5D_SELECTED');

  // The four selector summaries intentionally prefetch 5D. A direct 1321/5D
  // click may therefore reuse an already-verified cache and emit no request.
  // Persist the explicit selection, arm observers, then make the app perform
  // its normal reload/revalidation path. This is the causal trigger for R13.
  let response = null;
  const httpStatuses = [];
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const [request, observedResponse] = await triggerCanonicalRevalidation(page, timeout);
    httpStatuses.push(observedResponse.status());
    if (attempt === 1) {
      machine.transition('R14_CANONICAL_REQUEST_OBSERVED', {
        url: request.url(), httpStatus: observedResponse.status(),
      });
    }
    if (observedResponse.status() === 200
        || observedResponse.status() === 304) {
      response = observedResponse;
      break;
    }
    if (observedResponse.status() !== 429 || attempt === 3) {
      throw new Error(`canonical_1321_5d_http:${httpStatuses.join(',')}`);
    }
    await page.waitForTimeout(retryDelayMs(observedResponse));
  }
  if (!response) throw new Error('canonical_1321_5d_response_missing');
  // 200 carries a fresh verified body. 304 is the conditional-revalidation
  // outcome (v13.5.0 supplies If-None-Match from the intact verified cache):
  // the server thereby attests that the client's cached snapshot IS the
  // canonical one, and the ETag names its exact snapshot id. Both are
  // verified outcomes; a 304 must still bind response identity to the UI.
  let responseSnapshotId;
  let verificationStatus;
  let responseBodySource;
  if (response.status() === 304) {
    const etag = String((await response.allHeaders()).etag ?? '');
    responseSnapshotId = etag.replace(/^W\//i, '').replace(/"/g, '');
    if (!/^vs-[0-9a-f]{32}$/.test(responseSnapshotId)) {
      throw new Error('canonical_1321_5d_304_etag_invalid');
    }
    verificationStatus = 'verified';
    responseBodySource = 'not-modified-etag';
  } else {
    const captured = await readCanonicalResponseBody(page, timeout);
    const { body } = captured;
    const view = body?.payload || body;
    if (body?.verificationStatus !== 'verified'
        || !body?.snapshotId
        || (view?.automaticAiCalls ?? 0) !== 0) {
      throw new Error('canonical_1321_5d_response_not_verified');
    }
    responseSnapshotId = body.snapshotId;
    verificationStatus = body.verificationStatus;
    responseBodySource = captured.source;
  }
  if (expectedSnapshotId && responseSnapshotId !== expectedSnapshotId) {
    throw new Error('canonical_1321_5d_response_snapshot_mismatch');
  }
  machine.transition('R15_VERIFIED_SNAPSHOT_RECEIVED', {
    httpStatus: response.status(), httpStatuses, responseBodySource,
    snapshotId: responseSnapshotId,
  });

  await openCanonicalEvidence(page, timeout);
  await page.waitForFunction(({ selector, snapshotId }) => {
    const contract = document.querySelector(selector);
    return contract?.getAttribute('data-canonical-snapshot-id') === snapshotId
      && contract?.getAttribute('data-canonical-instrument') === '1321'
      && contract?.getAttribute('data-canonical-horizon') === '5D';
  }, { selector: CANONICAL_SNAPSHOT_SELECTOR, snapshotId: responseSnapshotId },
  { timeout });
  const contract = page.locator(CANONICAL_SNAPSHOT_SELECTOR);
  const uiSnapshotId = await contract.getAttribute('data-canonical-snapshot-id');
  machine.transition('R16_UI_SNAPSHOT_ID_MATCHED', {
    responseSnapshotId, uiSnapshotId,
  });
  return {
    canonicalHorizon: '5D',
    httpStatus: response.status(),
    httpStatuses,
    instrument: '1321',
    machine,
    responseSnapshotId,
    uiSnapshotId,
    verificationStatus,
  };
}
