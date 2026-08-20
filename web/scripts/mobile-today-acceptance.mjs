import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {
  CANONICAL_SNAPSHOT_SELECTOR,
  CANONICAL_PROJECTION_STATE_SELECTOR,
  openCanonicalEvidence,
  readCanonicalProjectionState,
  readCanonicalWarmRevalidationState,
  selectCanonical1321FiveDay,
  validateCanonicalWarmRevalidationTransition,
} from './canonical-snapshot-selection.mjs';

const PUBLIC_URL = process.env.ARGUS_PUBLIC_URL
  || 'http://127.0.0.1:4173/argus/';
const EXPECTED_VERSION = process.env.ARGUS_EXPECTED_VERSION || '';
const EXPECTED_SHA = process.env.ARGUS_EXPECTED_SHA || '';
const OUT_DIR = path.resolve(process.env.ARGUS_MOBILE_ACCEPTANCE_OUT
  || '/tmp/argus-mobile-today-acceptance');
const TODAY_URL = `${PUBLIC_URL.replace(/\/?$/, '/')}#today`;
const SYMBOLS = ['1321', '1306', 'SPY', 'QQQ'];
const HORIZONS = ['1D', '5D', '20D'];
const LOADER_THRESHOLD_MS = 225;
const LOADER_TIMING_TOLERANCE_MS = 1;
const COMBINATION_PACE_MS = 1_000;
const VIEWPORTS = [
  { width: 320, height: 568 }, { width: 375, height: 812 },
  { width: 390, height: 844 }, { width: 393, height: 852 },
  { width: 414, height: 896 }, { width: 430, height: 932 },
  { width: 932, height: 430 },
];
// The complete, ordered gate inventory of this engine. Every gate runs in
// every invocation — candidate target and production target execute the same
// list by construction, so no gate can exist that production discovers first.
const GATE_INVENTORY = [
  { id: 'M01', name: 'shell-identity-version-sha' },
  { id: 'M02', name: 'canonical-1321-5d-selection' },
  { id: 'M03', name: 'today-selector-four-instruments' },
  { id: 'M04', name: 'twelve-combination-verified-projection' },
  { id: 'M05', name: 'responsive-geometry-matrix' },
  { id: 'M06', name: 'navigation-history-active-state' },
  { id: 'M07', name: 'cold-loader-semantics' },
  { id: 'M08', name: 'slow-initial-label' },
  { id: 'M09', name: 'failure-retry-contract' },
  { id: 'M10', name: 'warm-revalidation-contract' },
  { id: 'M11', name: 'not-modified-continuity' },
  { id: 'M12', name: 'rate-limit-cache-backoff' },
  { id: 'M13', name: 'offline-snapshot-continuity' },
  { id: 'M14', name: 'request-hygiene-console-ai' },
  { id: 'M15', name: 'headline-first-decision-visibility' },
];
const sanitize = (value) => String(value ?? '')
  .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
  .replace(/([?&](?:token|key|authorization|auth)=[^&\s]+)/gi, '?redacted')
  .slice(0, 800);
const roundTimingMs = (value) => Number.isFinite(value)
  ? Math.round(value * 1_000) / 1_000 : null;

function classifyConsoleErrors(evidence) {
  const remaining429s = evidence.rateLimits
    .filter((row) => row.contractValid)
    .map((row) => row.url);
  const unexpected = [];
  const expected429 = [];
  const expectedOffline = [];
  for (const error of evidence.consoleErrors) {
    if (/ERR_INTERNET_DISCONNECTED/.test(error.message)) {
      expectedOffline.push(error);
      continue;
    }
    if (error.type !== 'console.error' || !/\b429\b/.test(error.message)) {
      unexpected.push(error);
      continue;
    }
    const index = remaining429s.findIndex((url) =>
      !error.location || error.location === url);
    if (index < 0) {
      unexpected.push(error);
      continue;
    }
    remaining429s.splice(index, 1);
    expected429.push(error);
  }
  return { unexpected, expected429, expectedOffline };
}

async function writeJson(name, value) {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(path.join(OUT_DIR, name), `${JSON.stringify(value, null, 2)}\n`);
}

// Every semantic wait publishes the actually observed contract state when it
// times out, so a failed gate always leaves machine-readable DOM evidence —
// never a bare stack trace.
const timeoutDiagnostics = [];
async function waitForContractState(page, gate, predicate, argument, timeout = 30_000) {
  try {
    await page.waitForFunction(predicate, argument, { timeout });
  } catch (error) {
    const observed = await page.evaluate(() => {
      const read = (selector) => [...document.querySelectorAll(selector)]
        .map((node) => Object.fromEntries([...node.attributes]
          .filter((attribute) => attribute.name.startsWith('data-'))
          .map((attribute) => [attribute.name, attribute.value])));
      return {
        projection: read('[data-argus-contract="today-projection-state-v1"]'),
        canonical: read('[data-argus-contract="canonical-market-snapshot-v1"]'),
      };
    }).catch(() => null);
    timeoutDiagnostics.push({ gate, observed, at: new Date().toISOString() });
    await writeJson('timeout-diagnostics.json', timeoutDiagnostics).catch(() => {});
    error.message = `${gate}: ${error.message} observed=${JSON.stringify(observed)}`;
    throw error;
  }
}

async function screenshot(page, name, fullPage = false) {
  await fs.mkdir(path.join(OUT_DIR, 'screenshots'), { recursive: true });
  await page.screenshot({
    path: path.join(OUT_DIR, 'screenshots', name),
    fullPage, animations: 'disabled', timeout: 15_000,
  });
}

function observe(page, evidence) {
  page.on('console', (message) => {
    const location = message.location().url || '';
    const isIntentionallyBlockedSupportGet = location.includes('/api/argus/')
      && !location.includes('/api/argus/chart-intelligence');
    if (message.type() === 'error' && !isIntentionallyBlockedSupportGet) {
      evidence.consoleErrors.push({
        type: 'console.error',
        location: sanitize(location),
        message: sanitize(message.text()),
      });
    }
    if (message.type() === 'warning' && /react/i.test(message.text())) {
      evidence.reactWarnings.push(sanitize(message.text()));
    }
  });
  page.on('pageerror', (error) => evidence.consoleErrors.push({
    type: 'pageerror', location: '', message: sanitize(error.message),
  }));
  page.on('request', (request) => {
    const url = new URL(request.url());
    evidence.network.push({
      method: request.method(), origin: url.origin, pathname: url.pathname,
      symbol: url.searchParams.get('symbol'),
      horizon: url.searchParams.get('horizon'),
      snapshot: url.searchParams.get('snapshot'),
      scope: url.searchParams.get('scope'),
    });
    if (request.method() === 'POST' && url.pathname.startsWith('/api/argus/')) {
      evidence.aiPostCount += 1;
    }
  });
  page.on('response', (response) => {
    const task = (async () => {
      const url = new URL(response.url());
      if (url.pathname !== '/api/argus/chart-intelligence') return;
      if (response.status() === 429) {
        let body = null;
        try { body = await response.json(); } catch { /* invalid contract is recorded below */ }
        const contractValid = body?.error === 'rate_limited'
          && typeof body?.message === 'string';
        evidence.rateLimits.push({
          url: response.url(), status: response.status(),
          retryAfter: response.headers()['retry-after'] ?? null,
          contractValid,
        });
        if (!contractValid) evidence.failures.push('rate-limit-response-contract');
        return;
      }
      if (response.status() !== 200) return;
      try {
        const body = await response.json();
        const symbol = url.searchParams.get('symbol');
        const horizon = url.searchParams.get('horizon');
        if (symbol && horizon) {
          evidence.snapshotBodies.set(`${symbol}:${horizon}`, JSON.stringify(body));
        }
        if ((body.payload?.automaticAiCalls ?? body.automaticAiCalls) !== 0) {
          evidence.failures.push(`automatic-ai:${url.searchParams.get('symbol')}`);
        }
      } catch { /* the UI verifier is authoritative for malformed responses */ }
    })();
    evidence.responseTasks.add(task);
    void task.then(
      () => evidence.responseTasks.delete(task),
      () => evidence.responseTasks.delete(task),
    );
  });
}

async function drainResponseTasks(evidence) {
  while (evidence.responseTasks.size) {
    await Promise.allSettled([...evidence.responseTasks]);
  }
}

async function isolateChartReads(context, evidence) {
  await context.route('**/api/argus/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/argus/chart-intelligence') {
      await route.continue(); return;
    }
    evidence.suppressedNonChartGets += 1;
    await route.abort('blockedbyclient');
  });
}

function fulfillCapturedSnapshot(route, evidence, delayMs) {
  const url = new URL(route.request().url());
  const key = `${url.searchParams.get('symbol')}:${url.searchParams.get('horizon')}`;
  const body = evidence.snapshotBodies.get(key);
  if (!body) return route.abort('failed');
  return new Promise((resolve) => setTimeout(resolve, delayMs))
    .then(() => route.fulfill({ status: 200, contentType: 'application/json', body }));
}

async function waitForShell(page) {
  await page.waitForSelector('.nav__mobile', { state: 'attached', timeout: 30_000 });
  if (EXPECTED_VERSION) {
    await page.waitForFunction((version) =>
      globalThis.__ARGUS_VERSION__ === version, EXPECTED_VERSION, { timeout: 30_000 });
  }
  if (EXPECTED_SHA) {
    await page.waitForFunction((sha) =>
      globalThis.__ARGUS_BUILD_SHA__ === sha, EXPECTED_SHA, { timeout: 30_000 });
  }
}

async function waitForTodayChart(page, timeout = 30_000) {
  await page.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .waitFor({ state: 'visible', timeout });
  await openCanonicalEvidence(page, timeout);
}

async function waitForCanonicalProjectionContract(page, timeout = 30_000) {
  await page.waitForFunction(({ projectionSelector, snapshotSelector }) => {
    const nodes = [...document.querySelectorAll(projectionSelector)];
    const snapshot = document.querySelector(snapshotSelector);
    if (nodes.length !== 1 || !snapshot) return false;
    const node = nodes[0];
    const state = node.getAttribute('data-projection-state');
    const snapshotId = node.getAttribute('data-projection-snapshot-id');
    const responseSnapshotId = node.getAttribute('data-projection-response-snapshot-id');
    const snapshotState = node.getAttribute('data-projection-snapshot-state');
    const canonicalSnapshotId = snapshot.getAttribute('data-canonical-snapshot-id');
    const canonicalResponseSnapshotId = snapshot.getAttribute(
      'data-canonical-response-snapshot-id');
    return ['available', 'missing'].includes(state)
      && snapshotId === canonicalSnapshotId
      && responseSnapshotId === canonicalResponseSnapshotId
      && snapshotState === snapshot.getAttribute('data-canonical-snapshot-state')
      && (!responseSnapshotId || responseSnapshotId === snapshotId);
  }, {
    projectionSelector: CANONICAL_PROJECTION_STATE_SELECTOR,
    snapshotSelector: '[data-argus-contract="canonical-market-snapshot-v1"]',
  }, { timeout });
}

async function selectCanonicalControls(page, timeout = 30_000) {
  await openCanonicalEvidence(page, timeout);
  await page.getByRole('group', { name: '表示市場' })
    .getByRole('button', { name: 'JP', exact: true }).click();
  await page.locator(
    '[data-argus-control="market-instrument"][data-instrument="1321"]',
  ).click();
  await page.locator(
    '[data-argus-control="canonical-horizon"][data-horizon="5D"]',
  ).click();
  await page.waitForFunction(() => {
    const contract = document.querySelector(
      '[data-argus-contract="canonical-market-snapshot-v1"]',
    );
    return contract?.getAttribute('data-canonical-instrument') === '1321'
      && contract?.getAttribute('data-canonical-horizon') === '5D'
      && contract?.getAttribute('data-canonical-verification') === 'verified';
  }, null, { timeout });
}

async function geometry(page, viewport) {
  // Chromium does not expose iOS env() values, so record the native value and
  // separately prove the runtime guard rejects an oversized installed-web-view
  // value before exercising the exact 34px maximum accepted by the contract.
  const hostileSafeAreaBottom = await page.evaluate(async () => {
    document.documentElement.style.setProperty('--argus-safe-bottom', '92px');
    window.dispatchEvent(new Event('pageshow'));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const bounded = parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--argus-safe-bottom'));
    document.documentElement.style.setProperty('--argus-safe-bottom', '34px');
    return bounded;
  });
  return page.evaluate((size) => {
    const rect = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const value = element.getBoundingClientRect();
      return {
        top: value.top, right: value.right, bottom: value.bottom,
        left: value.left, width: value.width, height: value.height,
      };
    };
    const probe = document.createElement('div');
    probe.style.cssText = 'position:fixed;visibility:hidden;padding-bottom:env(safe-area-inset-bottom,0px)';
    document.body.appendChild(probe);
    const nativeSafeAreaBottom = parseFloat(getComputedStyle(probe).paddingBottom) || 0;
    probe.remove();
    const vv = window.visualViewport;
    const visualViewportBottom = (vv?.offsetTop ?? 0) + (vv?.height ?? innerHeight);
    const navRect = rect('.nav');
    const stickyCommandRect = rect('.msc');
    const navButtons = [...document.querySelectorAll('.nav__mobile > button')];
    const navButtonRect = navButtons[0]?.getBoundingClientRect() ?? null;
    const navButtonPaddingBottom = navButtons[0]
      ? parseFloat(getComputedStyle(navButtons[0]).paddingBottom) || 0 : null;
    return {
      viewport: size,
      innerHeight, outerHeight,
      clientHeight: document.documentElement.clientHeight,
      visualViewportHeight: vv?.height ?? null,
      visualViewportOffsetTop: vv?.offsetTop ?? null,
      visualViewportWidth: vv?.width ?? null,
      nativeSafeAreaBottom,
      exercisedSafeAreaBottom: 34,
      hostileSafeAreaBottom: size.hostileSafeAreaBottom,
      navRect, stickyCommandRect,
      shellRect: rect('.shell'), bodyRect: rect('body'),
      mainRect: rect('.shell__main'),
      visualViewportBottom,
      distanceFromViewportBottom: navRect
        ? Math.abs(visualViewportBottom - navRect.bottom) : null,
      navControlBottomGap: navButtonRect
        ? visualViewportBottom - navButtonRect.bottom : null,
      navVisualBottomGap: navButtonRect && navButtonPaddingBottom != null
        ? visualViewportBottom - navButtonRect.bottom + navButtonPaddingBottom : null,
      stickyNavGap: navRect && stickyCommandRect
        ? navRect.top - stickyCommandRect.bottom : null,
      horizontalOverflow: document.body.scrollWidth
        > Math.ceil(vv?.width ?? innerWidth),
      bodyScrollWidth: document.body.scrollWidth,
      displayMode: matchMedia('(display-mode: standalone)').matches
        ? 'standalone' : 'browser',
      orientation: screen.orientation?.type
        ?? (innerWidth > innerHeight ? 'landscape' : 'portrait'),
      devicePixelRatio,
      navTouchTargets: [...document.querySelectorAll('.nav__mobile > button, .nav__mobile > details > summary')]
        .map((element) => element.getBoundingClientRect().height),
    };
  }, { ...viewport, hostileSafeAreaBottom });
}

async function navigationAudit(page, evidence) {
  const sequence = [
    ['Today', '#today'], ['Holdings', '#holdings'],
    ['Alerts', '#notifications'], ['Settings', '#settings'],
  ];
  const records = [];
  for (const [index, [name, hash]] of sequence.entries()) {
    await page.locator('.nav__mobile').getByRole('button', { name, exact: true }).click();
    await page.waitForFunction((expected) => location.hash === expected, hash);
    if (index > 0) {
      await page.waitForFunction(() =>
        document.querySelector('.shell__page')?.classList.contains('shell__page--next'));
    }
    records.push({
      name, hash: await page.evaluate(() => location.hash),
      active: await page.locator('.nav__mobile-btn.is-active').innerText(),
      direction: index === 0 ? null : 'next',
    });
  }
  await page.goBack(); await page.waitForFunction(() => location.hash === '#notifications');
  await page.waitForFunction(() =>
    document.querySelector('.shell__page')?.classList.contains('shell__page--prev'));
  const back = await page.locator('.nav__mobile-btn.is-active').innerText();
  await page.goForward(); await page.waitForFunction(() => location.hash === '#settings');
  await page.waitForFunction(() =>
    document.querySelector('.shell__page')?.classList.contains('shell__page--next'));
  const forward = await page.locator('.nav__mobile-btn.is-active').innerText();
  await screenshot(page, 'settings-navigation.png');
  if (records.some((record, index) =>
    record.hash !== sequence[index][1] || record.active !== sequence[index][0])) {
    evidence.failures.push('navigation-order-or-active-state');
  }
  if (back !== 'Alerts' || forward !== 'Settings') {
    evidence.failures.push('history-navigation-active-state');
  }
  return { records, back, forward, systemVisible: false };
}

async function run() {
  await fs.rm(OUT_DIR, { recursive: true, force: true });
  const evidence = {
    failures: [], consoleErrors: [], reactWarnings: [], network: [],
    aiPostCount: 0, geometry: [], combinations: [],
    snapshotBodies: new Map(), suppressedNonChartGets: 0, rateLimits: [],
    responseTasks: new Set(),
  };
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 430, height: 932 },
    deviceScaleFactor: 3, isMobile: true, hasTouch: true,
    serviceWorkers: 'allow',
  });
  await isolateChartReads(context, evidence);
  const page = await context.newPage();
  observe(page, evidence);
  const initialRequestsAt = evidence.network.length;
  await page.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(page);
  const selector = page.locator('[data-argus-control="market-instrument"]');
  await selector.first().waitFor({ state: 'attached', timeout: 30_000 });
  await selectCanonical1321FiveDay(page);
  if (await selector.count() !== 4) evidence.failures.push('today-selector-not-four');
  const initialChartRequests = evidence.network.slice(initialRequestsAt)
    .filter((row) => row.pathname === '/api/argus/chart-intelligence');
  const initialKeys = new Set(initialChartRequests.map(
    (row) => `${row.symbol}:${row.horizon}:${row.snapshot}:${row.scope}`));
  for (const symbol of SYMBOLS) {
    await page.locator(
      `[data-argus-control="market-instrument"][data-instrument="${symbol}"]`,
    ).click();
    for (const horizon of HORIZONS) {
      await page.locator(
        `[data-argus-control="canonical-horizon"][data-horizon="${horizon}"]`,
      ).click();
      await waitForTodayChart(page);
      await page.waitForFunction(({ expectedSymbol, expectedHorizon }) => {
        const contract = document.querySelector(
          '[data-argus-contract="canonical-market-snapshot-v1"]',
        );
        return contract?.getAttribute('data-canonical-instrument') === expectedSymbol
          && contract?.getAttribute('data-canonical-horizon') === expectedHorizon
          && contract?.getAttribute('data-canonical-verification') === 'verified';
      }, { expectedSymbol: symbol, expectedHorizon: horizon }, { timeout: 30_000 });
      await waitForCanonicalProjectionContract(page);
      const record = await page.evaluate(({ expectedSymbol, expectedHorizon }) => ({
        symbol: document.querySelector('.at-proj-heading b')?.textContent ?? '',
        horizon: document.querySelector('.at-horizon button[aria-pressed="true"]')?.textContent ?? '',
        snapshotId: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-snapshot-id'),
        snapshotState: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-snapshot-state'),
        verification: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-verification'),
        responseSnapshotId: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-response-snapshot-id'),
        canonicalInstrument: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-instrument'),
        canonicalHorizon: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-horizon'),
        expectedSymbol, expectedHorizon,
      }), { expectedSymbol: symbol, expectedHorizon: horizon });
      evidence.combinations.push(record);
      if (record.horizon !== horizon || !record.snapshotId
          || record.verification !== 'verified'
          || record.canonicalInstrument !== symbol
          || record.canonicalHorizon !== horizon) {
        evidence.failures.push(`today-combination:${symbol}:${horizon}`);
      }
      const projectionState = await readCanonicalProjectionState(page, {
        expectedSnapshotId: record.snapshotId,
        expectedSnapshotState: record.snapshotState,
        acceptedResponseSnapshotId: record.responseSnapshotId,
      });
      if (!projectionState.pass) {
        evidence.failures.push(`today-projection-state:${symbol}:${horizon}:${projectionState.reason}`);
      }
      // The UI is intentionally exercised as a single human interaction
      // stream. One request at a time plus explicit pacing avoids turning a
      // public-acceptance run into a synthetic request storm.
      await page.waitForTimeout(COMBINATION_PACE_MS);
    }
    await screenshot(page, `today-${symbol}.png`);
  }

  await page.setViewportSize({ width: 430, height: 932 });
  await page.locator('.nav__mobile').getByRole('button', { name: 'Today', exact: true }).click();
  for (const viewport of VIEWPORTS) {
    await page.setViewportSize(viewport);
    const audit = await geometry(page, viewport);
    evidence.geometry.push(audit);
    if ((audit.distanceFromViewportBottom ?? 99) > 1) {
      evidence.failures.push(`nav-bottom:${viewport.width}`);
    }
    if (viewport.width <= 720 && Math.abs(audit.stickyNavGap ?? 99) > 1) {
      evidence.failures.push(`sticky-gap:${viewport.width}`);
    }
    if (viewport.width <= 720
      && ((audit.navVisualBottomGap ?? 99) < 18
        || (audit.navVisualBottomGap ?? 99) > 24)) {
      evidence.failures.push(`nav-visual-bottom-gap:${viewport.width}`);
    }
    if (!Number.isFinite(audit.hostileSafeAreaBottom)
      || audit.hostileSafeAreaBottom < 0 || audit.hostileSafeAreaBottom > 34) {
      evidence.failures.push(`safe-area-bound:${viewport.width}`);
    }
    if (audit.horizontalOverflow) evidence.failures.push(`horizontal-overflow:${viewport.width}`);
    if (viewport.width <= 720 && audit.navTouchTargets.some((height) => height < 44)) {
      evidence.failures.push(`touch-target:${viewport.width}`);
    }
  }
  await page.setViewportSize({ width: 430, height: 932 });
  await screenshot(page, 'iphone-14-pro-max-full.png', true);
  await screenshot(page, 'iphone-14-pro-max-bottom-nav.png');
  const navigation = await navigationAudit(page, evidence);

  // Cold Today: no IndexedDB/SW, controlled 4s network delay. The chart footprint remains
  // stable and TriangleStepLoader must appear after the 225ms threshold.
  const cold = await browser.newContext({
    viewport: { width: 430, height: 932 }, serviceWorkers: 'block',
  });
  await cold.addInitScript(() => {
    globalThis.__ARGUS_LOADER_FIRST_AT__ = null;
    const observe = () => {
      const root = document.documentElement;
      if (!root) return;
      const record = () => {
        if (globalThis.__ARGUS_LOADER_FIRST_AT__ == null
            && document.querySelector('.at-projection-missing .triangle-step-loader')) {
          globalThis.__ARGUS_LOADER_FIRST_AT__ = performance.now();
        }
      };
      new MutationObserver(record).observe(root, { childList: true, subtree: true });
      record();
    };
    if (document.documentElement) observe();
    else document.addEventListener('DOMContentLoaded', observe, { once: true });
  });
  await isolateChartReads(cold, evidence);
  await cold.route('**/api/argus/chart-intelligence?*',
    (route) => fulfillCapturedSnapshot(route, evidence, 4_000));
  const coldPage = await cold.newPage();
  const coldLoaderAppeared = coldPage.locator(
    '.at-projection-missing .triangle-step-loader',
  ).waitFor({ state: 'visible', timeout: 5_000 });
  await coldPage.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(coldPage);
  await openCanonicalEvidence(coldPage);
  await coldLoaderAppeared;
  const coldSemanticState = await readCanonicalWarmRevalidationState(coldPage, {
    expectedRevalidationState: 'cold-loading',
    acceptedResponseSnapshotId: null,
  });
  const loaderTiming = await coldPage.evaluate(() => {
    // The 225ms no-flash threshold is about PERCEIVED waiting, which begins
    // when the view starts loading (navigation-start), not when the network
    // request is dispatched — since v13.5.0 revalidation deliberately starts
    // after the cache lookup so If-None-Match can be supplied.
    const entries = performance.getEntriesByName(
      'argus-snapshot:navigation-start');
    const loadingStart = entries.length ? entries[entries.length - 1].startTime : null;
    const firstLoaderAt = globalThis.__ARGUS_LOADER_FIRST_AT__;
    return {
      loadingStart,
      firstLoaderAt,
      rawDelayMs: loadingStart != null && firstLoaderAt != null
        ? firstLoaderAt - loadingStart : null,
    };
  });
  loaderTiming.roundedDelayMs = roundTimingMs(loaderTiming.rawDelayMs);
  loaderTiming.thresholdMs = LOADER_THRESHOLD_MS;
  loaderTiming.toleranceMs = LOADER_TIMING_TOLERANCE_MS;
  const before225 = loaderTiming.roundedDelayMs != null
    && loaderTiming.roundedDelayMs < LOADER_THRESHOLD_MS - LOADER_TIMING_TOLERANCE_MS
    ? 1 : 0;
  const after225 = await coldPage.locator(
    '.at-projection-missing .triangle-step-loader').count();
  const skeletonHeight = await coldPage.locator('.at-projection-missing').evaluate(
    (element) => element.getBoundingClientRect().height);
  await screenshot(coldPage, 'today-cold-loader.png');
  if (!coldSemanticState.pass || loaderTiming.roundedDelayMs == null || before225
      || !after225 || skeletonHeight < 250) {
    evidence.failures.push('cold-loader-contract');
  }
  await cold.close();

  // A six-second cold delay must expose the explicit initial preparation label.
  const slow = await browser.newContext({
    viewport: { width: 430, height: 932 }, serviceWorkers: 'block',
  });
  await isolateChartReads(slow, evidence);
  await slow.route('**/api/argus/chart-intelligence?*',
    (route) => fulfillCapturedSnapshot(route, evidence, 6_000));
  const slowPage = await slow.newPage();
  const slowStateAppeared = slowPage.waitForFunction(({ selector }) => {
    const nodes = [...document.querySelectorAll(selector)];
    if (nodes.length !== 1) return false;
    const node = nodes[0];
    if (node.getAttribute('data-projection-state') !== 'missing'
        || node.getAttribute('data-projection-snapshot-id')
        || node.getAttribute('data-projection-response-snapshot-id')
        || node.getAttribute('data-projection-snapshot-state') !== 'NO_CACHE_LOADING'
        || !node.textContent?.includes('初回データを準備中')) return false;
    return {
      state: 'missing',
      snapshotState: 'NO_CACHE_LOADING',
      label: '初回データを準備中',
    };
  }, { selector: CANONICAL_PROJECTION_STATE_SELECTOR }, { timeout: 7_000 });
  await slowPage.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(slowPage);
  await openCanonicalEvidence(slowPage);
  const slowState = await slowStateAppeared.then((handle) => handle.jsonValue());
  const slowLabel = slowState?.label ?? null;
  if (slowState?.state !== 'missing' || slowState?.label !== '初回データを準備中') {
    evidence.failures.push('slow-label');
  }
  await slow.close();

  // A failed cold request terminates the loader and leaves an actionable retry.
  const failure = await browser.newContext({
    viewport: { width: 430, height: 932 }, serviceWorkers: 'block',
  });
  await isolateChartReads(failure, evidence);
  await failure.route('**/api/argus/chart-intelligence?*',
    (route) => route.fulfill({ status: 500, contentType: 'application/json',
      body: '{"error":"controlled"}' }));
  const failurePage = await failure.newPage();
  await failurePage.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(failurePage);
  await openCanonicalEvidence(failurePage);
  await failurePage.locator('.at-projection-missing')
    .getByRole('button', { name: '再試行' })
    .waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {});
  const failureState = {
    loader: await failurePage.locator('.at-projection-missing .triangle-step-loader').count(),
    retry: await failurePage.locator('.at-projection-missing')
      .getByRole('button', { name: '再試行' }).count(),
  };
  if (failureState.loader || !failureState.retry) evidence.failures.push('failure-loader-contract');
  await failure.close();

  // Warm cache is the immediate visible authority while a controlled network
  // request revalidates in the background. Presentation loaders are optional;
  // this gate observes semantic state and exact snapshot identity only.
  // IndexedDB remains intact across seed and reload within this context.
  await page.setViewportSize({ width: 430, height: 932 });
  await page.locator('.nav__mobile').getByRole('button', { name: 'Today', exact: true }).click();
  await selectCanonical1321FiveDay(page);
  const onlineSnapshotId = await page.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .getAttribute('data-canonical-snapshot-id');
  const warm = await browser.newContext({
    viewport: { width: 430, height: 932 }, serviceWorkers: 'block',
  });
  await isolateChartReads(warm, evidence);
  await warm.route('**/api/argus/chart-intelligence?*',
    (route) => fulfillCapturedSnapshot(route, evidence, 0));
  const warmPage = await warm.newPage();
  observe(warmPage, evidence);
  await warmPage.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(warmPage);
  await selectCanonicalControls(warmPage);
  const warmSeedSnapshotId = await warmPage.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .getAttribute('data-canonical-snapshot-id');
  await warm.unroute('**/api/argus/chart-intelligence?*');
  let resolveWarmRequestStart;
  const warmRequestStart = new Promise((resolve) => {
    resolveWarmRequestStart = resolve;
  });
  let releaseWarmResponse;
  const warmResponseRelease = new Promise((resolve) => {
    releaseWarmResponse = resolve;
  });
  await warm.route('**/api/argus/chart-intelligence?*', async (route) => {
    resolveWarmRequestStart?.(Date.now());
    resolveWarmRequestStart = null;
    await warmResponseRelease;
    return fulfillCapturedSnapshot(route, evidence, 0);
  });
  await warmPage.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(warmPage);
  await waitForTodayChart(warmPage);
  await Promise.race([
    warmRequestStart,
    new Promise((_, reject) => setTimeout(
      () => reject(new Error('controlled warm revalidation did not start')),
      5_000)),
  ]);
  await waitForContractState(warmPage, 'warm-revalidation-background',
    ({ selector, snapshotId }) => {
      const nodes = [...document.querySelectorAll(selector)];
      if (nodes.length !== 1) return false;
      const node = nodes[0];
      return node.getAttribute('data-projection-state') === 'available'
        && node.getAttribute('data-projection-revalidation-state') === 'background'
        && node.getAttribute('data-projection-snapshot-state') === 'CACHE_READY_REVALIDATING'
        && node.getAttribute('data-projection-snapshot-id') === snapshotId
        && !node.getAttribute('data-projection-response-snapshot-id');
    }, { selector: CANONICAL_PROJECTION_STATE_SELECTOR, snapshotId: warmSeedSnapshotId });
  const warmRevalidating = await readCanonicalWarmRevalidationState(warmPage, {
    expectedRevalidationState: 'background',
    cachedSnapshotId: warmSeedSnapshotId,
    acceptedResponseSnapshotId: null,
  });
  await screenshot(warmPage, 'today-warm-revalidation-cached.png');
  releaseWarmResponse();
  await waitForContractState(warmPage, 'warm-revalidation-settled',
    ({ selector, snapshotId }) => {
      const nodes = [...document.querySelectorAll(selector)];
      if (nodes.length !== 1) return false;
      const node = nodes[0];
      return node.getAttribute('data-projection-state') === 'available'
        && node.getAttribute('data-projection-revalidation-state') === 'settled'
        && node.getAttribute('data-projection-snapshot-state') === 'CURRENT_READY'
        && node.getAttribute('data-projection-snapshot-id') === snapshotId
        && node.getAttribute('data-projection-response-snapshot-id') === snapshotId;
    }, { selector: CANONICAL_PROJECTION_STATE_SELECTOR, snapshotId: warmSeedSnapshotId });
  const warmSettled = await readCanonicalWarmRevalidationState(warmPage, {
    expectedRevalidationState: 'settled',
    cachedSnapshotId: warmSeedSnapshotId,
    acceptedResponseSnapshotId: warmSeedSnapshotId,
  });
  const warmTransition = validateCanonicalWarmRevalidationTransition({
    cachedSnapshotId: warmSeedSnapshotId,
    revalidatingNodes: [{
      state: 'available', snapshotId: warmRevalidating.snapshotId,
      responseSnapshotId: warmRevalidating.responseSnapshotId,
      snapshotState: warmRevalidating.snapshotState,
      revalidationState: warmRevalidating.state,
    }],
    finalNodes: [{
      state: 'available', snapshotId: warmSettled.snapshotId,
      responseSnapshotId: warmSettled.responseSnapshotId,
      snapshotState: warmSettled.snapshotState,
      revalidationState: warmSettled.state,
    }],
    acceptedResponseSnapshotId: warmSeedSnapshotId,
  });
  await warm.unroute('**/api/argus/chart-intelligence?*');
  if (!warmRevalidating.pass || !warmSettled.pass || !warmTransition.pass) {
    evidence.failures.push('warm-revalidation-contract');
  }

  const before304 = await warmPage.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .getAttribute('data-canonical-snapshot-id');
  await warm.route('**/api/argus/chart-intelligence?*',
    (route) => route.fulfill({ status: 304, body: '' }));
  await warmPage.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(warmPage); await waitForTodayChart(warmPage);
  const after304 = await warmPage.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .getAttribute('data-canonical-snapshot-id');
  await warm.unroute('**/api/argus/chart-intelligence?*');
  if (!warmSeedSnapshotId || before304 !== warmSeedSnapshotId
      || after304 !== before304) {
    evidence.failures.push('not-modified-continuity');
  }
  await warm.close();

  // A real 429 is an expected HTTP outcome, not a JavaScript/React exception.
  // With a verified cached snapshot the UI must remain usable, honor the
  // bounded retry window, and avoid an immediate retry storm.
  const rateLimitContext = await browser.newContext({
    viewport: { width: 430, height: 932 }, serviceWorkers: 'block',
  });
  await isolateChartReads(rateLimitContext, evidence);
  await rateLimitContext.route('**/api/argus/chart-intelligence?*',
    (route) => fulfillCapturedSnapshot(route, evidence, 0));
  const rateLimitPage = await rateLimitContext.newPage();
  observe(rateLimitPage, evidence);
  await rateLimitPage.goto(TODAY_URL, {
    waitUntil: 'domcontentloaded', timeout: 30_000,
  });
  await waitForShell(rateLimitPage);
  await selectCanonicalControls(rateLimitPage);
  const rateLimitSeedSnapshotId = await rateLimitPage.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .getAttribute('data-canonical-snapshot-id');
  await rateLimitContext.unroute('**/api/argus/chart-intelligence?*');
  let controlled429Calls = 0;
  await rateLimitContext.route('**/api/argus/chart-intelligence?*', (route) => {
    controlled429Calls += 1;
    return route.fulfill({
      status: 429, contentType: 'application/json',
      headers: { 'Retry-After': '2' },
      body: '{"error":"rate_limited","message":"controlled acceptance limit"}',
    });
  });
  await rateLimitPage.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(rateLimitPage); await waitForTodayChart(rateLimitPage);
  const rateLimitedSnapshotId = await rateLimitPage.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .getAttribute('data-canonical-snapshot-id');
  await waitForContractState(rateLimitPage, 'rate-limit-cached-safe',
    ({ selector, snapshotId }) => {
      const nodes = [...document.querySelectorAll(selector)];
      return nodes.length === 1
        && nodes[0].getAttribute('data-projection-revalidation-state') === 'cached-safe'
        && nodes[0].getAttribute('data-projection-snapshot-id') === snapshotId;
    }, { selector: CANONICAL_PROJECTION_STATE_SELECTOR,
      snapshotId: rateLimitSeedSnapshotId });
  const rateLimitedSemanticState = await readCanonicalWarmRevalidationState(
    rateLimitPage, {
      expectedRevalidationState: 'cached-safe',
      cachedSnapshotId: rateLimitSeedSnapshotId,
      acceptedResponseSnapshotId: null,
    });
  await rateLimitContext.unroute('**/api/argus/chart-intelligence?*');
  // v13.5.0: only the SELECTED instrument loads its heavy verified snapshot;
  // the other three come from the compact headline bootstrap. A reload with a
  // controlled 429 therefore produces exactly one bounded verified request.
  const controlledRateLimit = {
    calls: controlled429Calls,
    expectedCalls: 1,
    retryAfterSeconds: 2,
    seedSnapshotId: rateLimitSeedSnapshotId,
    cachedSnapshotId: rateLimitedSnapshotId,
  };
  if (!rateLimitedSemanticState.pass || controlled429Calls !== 1
      || !rateLimitSeedSnapshotId
      || rateLimitedSnapshotId !== rateLimitSeedSnapshotId) {
    evidence.failures.push('rate-limit-cache-backoff-contract');
  }
  // Playwright emits response events asynchronously. Drain the body-contract
  // readers before closing their context so a valid controlled 429 cannot be
  // misclassified merely because response.json() lost its page mid-read.
  await drainResponseTasks(evidence);
  await rateLimitContext.close();

  // The warmed verified snapshot must survive a fully offline reload.
  await context.setOffline(true);
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(page);
  await waitForTodayChart(page);
  const offlineSnapshotId = await page.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .getAttribute('data-canonical-snapshot-id');
  await screenshot(page, 'today-offline-cached.png');
  await context.setOffline(false);
  if (!onlineSnapshotId || offlineSnapshotId !== onlineSnapshotId) {
    evidence.failures.push('offline-snapshot-continuity');
  }

  // M15 — headline-first decision visibility: with every heavy verified
  // chart request held open, the four headline charts and their canonical
  // probabilities must still appear from the compact bootstrap. This is the
  // structural regression gate for "decision info hidden behind heavy
  // visualization payloads".
  let releaseHeavyHold;
  const heavyHold = new Promise((resolve) => { releaseHeavyHold = resolve; });
  const headlineContext = await browser.newContext({
    viewport: { width: 430, height: 932 }, serviceWorkers: 'block',
  });
  let heldHeavyRequests = 0;
  await headlineContext.route('**/api/argus/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/argus/today-headline') return route.continue();
    if (url.pathname === '/api/argus/chart-intelligence') {
      heldHeavyRequests += 1;
      await heavyHold;
      return fulfillCapturedSnapshot(route, evidence, 0);
    }
    evidence.suppressedNonChartGets += 1;
    return route.abort('blockedbyclient');
  });
  const headlinePage = await headlineContext.newPage();
  observe(headlinePage, evidence);
  await headlinePage.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(headlinePage);
  try {
    // v13.5.1 contract: four NAME selectors + the single selected projection
    // chart rendered from the compact headline (data-projection-source), with
    // its canonical probability row, all while heavy requests stay held.
    await waitForContractState(headlinePage, 'headline-first-decision-visibility',
      () => {
        const selectors = document.querySelectorAll(
          '[data-argus-control="market-instrument"]');
        const projection = document.querySelector(
          '[data-argus-contract="today-projection-state-v1"]');
        const probabilityRow = document.querySelector('.at-proj-prob');
        const primary = document.querySelector('.at-call strong');
        return selectors.length === 4
          && projection?.getAttribute('data-projection-state') === 'available'
          && projection?.getAttribute('data-projection-source') === 'headline'
          && !!probabilityRow
          && !!primary && (primary.textContent ?? '').trim().length > 0;
      }, null);
    evidence.headlineFirst = {
      pass: true, heldHeavyRequests,
      headlineVisibleWhileHeavyHeld: true,
    };
  } catch (error) {
    evidence.headlineFirst = { pass: false, heldHeavyRequests,
      error: sanitize(error instanceof Error ? error.message : error) };
    evidence.failures.push('headline-first-decision-visibility');
  }
  releaseHeavyHold();
  await drainResponseTasks(evidence);
  await headlineContext.close();

  const verifiedRequests = evidence.network.filter(
    (row) => row.pathname === '/api/argus/chart-intelligence');
  if (verifiedRequests.some((row) =>
    row.snapshot !== 'verified' || row.scope !== 'market')) {
    evidence.failures.push('legacy-chart-request');
  }
  for (const symbol of SYMBOLS) {
    for (const horizon of HORIZONS) {
      if (!verifiedRequests.some((row) =>
        row.symbol === symbol && row.horizon === horizon)) {
        evidence.failures.push(`request-missing:${symbol}:${horizon}`);
      }
    }
  }
  if (evidence.aiPostCount) evidence.failures.push(`ai-post:${evidence.aiPostCount}`);
  await drainResponseTasks(evidence);
  const consoleClassification = classifyConsoleErrors(evidence);
  if (consoleClassification.unexpected.length) evidence.failures.push('console-errors');
  if (evidence.reactWarnings.length) evidence.failures.push('react-warnings');

  const result = {
    verdict: evidence.failures.length ? 'FAIL' : 'PASS',
    testedAt: new Date().toISOString(),
    gateInventory: GATE_INVENTORY,
    publicUrl: TODAY_URL,
    frontendVersion: await page.evaluate(() => globalThis.__ARGUS_VERSION__ ?? null),
    frontendSha: await page.evaluate(() => globalThis.__ARGUS_BUILD_SHA__ ?? null),
    selectorSymbols: SYMBOLS,
    combinationCount: evidence.combinations.length,
    initialVerifiedRequestKeys: [...initialKeys].sort(),
    initialVerifiedRequestCount: initialKeys.size,
    navigation,
    loader: {
      before225, after225, skeletonHeight, slowLabel, failureState,
      loaderTiming,
    },
    warmRevalidation: { warmRevalidating, warmSettled, warmTransition },
    headlineFirst: evidence.headlineFirst,
    offline: { onlineSnapshotId, offlineSnapshotId, before304, after304 },
    rateLimit: {
      responses: evidence.rateLimits,
      expectedConsoleErrors: consoleClassification.expected429,
      controlled: controlledRateLimit,
    },
    suppressedNonChartGets: evidence.suppressedNonChartGets,
    failures: [...new Set(evidence.failures)].sort(),
  };
  await writeJson('acceptance.json', result);
  await writeJson('geometry.json', evidence.geometry);
  await writeJson('network.json', {
    aiPostCount: evidence.aiPostCount, requests: evidence.network,
  });
  await writeJson('console.json', {
    errors: consoleClassification.unexpected,
    expectedRateLimitErrors: consoleClassification.expected429,
    expectedOfflineErrors: consoleClassification.expectedOffline,
    reactWarnings: evidence.reactWarnings,
  });
  await writeJson('combinations.json', evidence.combinations);
  await context.close();
  await browser.close();
  if (evidence.failures.length) {
    throw new Error(`mobile Today acceptance failed: ${result.failures.join(', ')}`);
  }
  console.log(`mobile-today-acceptance: PASS (${evidence.combinations.length} combinations)`);
}

run().catch(async (error) => {
  const message = sanitize(error instanceof Error ? error.stack : error);
  try {
    await writeJson('fatal.json', { testedAt: new Date().toISOString(), error: message });
  } catch { /* preserve original failure */ }
  console.error(message);
  process.exit(1);
});
