import { seedStateMachine } from './release-state-machine.mjs';

export const CANONICAL_SNAPSHOT_SELECTOR =
  '[data-argus-contract="canonical-market-snapshot-v1"]'
  + '[data-canonical-verification="verified"]'
  + '[data-canonical-snapshot-id]';

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

export async function selectCanonical1321FiveDay(page, {
  expectedSnapshotId = null,
  timeout = 30_000,
  onTransition = () => {},
} = {}) {
  const machine = seedStateMachine(onTransition);
  await openCanonicalEvidence(page, timeout);
  machine.transition('R10_PRODUCT_SELECTION_READY');

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
    await stagingInstrument.click();
    await page.waitForFunction(() => document.querySelector(
      '[data-argus-control="market-instrument"][data-instrument="1306"]',
    )?.getAttribute('aria-pressed') === 'true', null, { timeout });
  }
  if (await canonicalHorizon.getAttribute('aria-pressed') === 'true') {
    const stagingHorizon = page.locator(
      '[data-argus-control="canonical-horizon"][data-horizon="1D"]',
    );
    await stagingHorizon.click();
    await page.waitForFunction(() => document.querySelector(
      '[data-argus-control="canonical-horizon"][data-horizon="1D"]',
    )?.getAttribute('aria-pressed') === 'true', null, { timeout });
  }

  const marketGroup = page.getByRole('group', { name: '表示市場' });
  await marketGroup.getByRole('button', { name: 'JP', exact: true }).click();
  await canonicalInstrument.click();
  await page.waitForFunction(() => document.querySelector(
    '[data-argus-control="market-instrument"][data-instrument="1321"]',
  )?.getAttribute('aria-pressed') === 'true', null, { timeout });
  machine.transition('R11_1321_SELECTED');
  await canonicalHorizon.click();
  await page.waitForFunction(() => document.querySelector(
    '[data-argus-control="canonical-horizon"][data-horizon="5D"]',
  )?.getAttribute('aria-pressed') === 'true', null, { timeout });
  machine.transition('R12_5D_SELECTED');

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
      machine.transition('R13_CANONICAL_REQUEST_OBSERVED', {
        url: request.url(), httpStatus: observedResponse.status(),
      });
    }
    if (observedResponse.status() === 200) {
      response = observedResponse;
      break;
    }
    if (observedResponse.status() !== 429 || attempt === 3) {
      throw new Error(`canonical_1321_5d_http:${httpStatuses.join(',')}`);
    }
    await page.waitForTimeout(retryDelayMs(observedResponse));
  }
  if (!response) throw new Error('canonical_1321_5d_response_missing');
  const body = await response.json();
  const view = body?.payload || body;
  if (body?.verificationStatus !== 'verified'
      || !body?.snapshotId
      || (view?.automaticAiCalls ?? 0) !== 0) {
    throw new Error('canonical_1321_5d_response_not_verified');
  }
  if (expectedSnapshotId && body.snapshotId !== expectedSnapshotId) {
    throw new Error('canonical_1321_5d_response_snapshot_mismatch');
  }
  machine.transition('R14_VERIFIED_SNAPSHOT_RECEIVED', {
    httpStatus: response.status(), httpStatuses, snapshotId: body.snapshotId,
  });

  await openCanonicalEvidence(page, timeout);
  await page.waitForFunction(({ selector, snapshotId }) => {
    const contract = document.querySelector(selector);
    return contract?.getAttribute('data-canonical-snapshot-id') === snapshotId
      && contract?.getAttribute('data-canonical-instrument') === '1321'
      && contract?.getAttribute('data-canonical-horizon') === '5D';
  }, { selector: CANONICAL_SNAPSHOT_SELECTOR, snapshotId: body.snapshotId },
  { timeout });
  const contract = page.locator(CANONICAL_SNAPSHOT_SELECTOR);
  const uiSnapshotId = await contract.getAttribute('data-canonical-snapshot-id');
  machine.transition('R15_SAME_SNAPSHOT_PROJECTED_TO_UI', {
    responseSnapshotId: body.snapshotId, uiSnapshotId,
  });
  return {
    canonicalHorizon: '5D',
    httpStatus: response.status(),
    httpStatuses,
    instrument: '1321',
    machine,
    responseSnapshotId: body.snapshotId,
    uiSnapshotId,
    verificationStatus: body.verificationStatus,
  };
}
