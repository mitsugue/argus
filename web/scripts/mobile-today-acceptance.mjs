import { createBrowserOwner, isOwnerCeremony, verifiedStoreFingerprint } from './owner-browser-acceptance.mjs';
import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {
  CANONICAL_SNAPSHOT_SELECTOR,
  CANONICAL_PROJECTION_STATE_SELECTOR,
  openCanonicalEvidence,
  readCanonicalProjectionState,
  readCanonicalWarmRevalidationState,
  selectCanonical1321FiveDay as selectCanonicalWithReload,
  validateCanonicalWarmRevalidationTransition,
} from './canonical-snapshot-selection.mjs';

const PUBLIC_URL = process.env.ARGUS_PUBLIC_URL
  || 'http://127.0.0.1:4173/argus/';
const EXPECTED_VERSION = process.env.ARGUS_EXPECTED_VERSION || '';
const EXPECTED_SHA = process.env.ARGUS_EXPECTED_SHA || '';
const OUT_DIR = path.resolve(process.env.ARGUS_MOBILE_ACCEPTANCE_OUT
  || '/tmp/argus-mobile-today-acceptance');
const BACKEND_ORIGIN = (process.env.ARGUS_BACKEND_URL || 'https://argus-backend-3j2m.onrender.com').replace(/\/$/, '');
const owner = createBrowserOwner({ baseUrl: BACKEND_ORIGIN, publicUrl: PUBLIC_URL });
const selectCanonical1321FiveDay = page => selectCanonicalWithReload(page, {
  beforeReload: owner.logout, afterReload: owner.login,
});
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
  { id: 'M03', name: 'today-single-nikkei-outlook' },
  { id: 'M04', name: 'twelve-research-snapshots-retained-off-surface' },
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
const sanitize = (value) => owner.redact(value)
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
  await page.screenshot({ mask: [page.locator('input[type=password]')],
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
    if (request.method() === 'POST' && url.pathname.startsWith('/api/argus/')
        && !(owner.enabled && isOwnerCeremony(url.href, BACKEND_ORIGIN, request.method()))) {
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
    if (owner.enabled && isOwnerCeremony(url.href, BACKEND_ORIGIN, route.request().method())) return route.continue();
    if (url.pathname === '/api/argus/chart-intelligence') {
      await route.continue(); return;
    }
    evidence.suppressedNonChartGets += 1;
    await route.abort('blockedbyclient');
  });
}

function controlledOwnerHeaders(route) {
  // A controlled response must carry the backend's own CORS contract: the
  // owner transport reads the echoed nonce, and a cross-origin page can read
  // that header only when it is exposed (argus_owner_auth adds
  // Access-Control-Expose-Headers: X-ARGUS-OWNER-NONCE). Without it the product
  // correctly treated the controlled 500 as an unproven response and locked
  // itself (2026-10-01, failure context: locked after a correct re-login).
  const headers = route.request().headers();
  const nonce = headers['x-argus-owner-nonce'];
  const cors = headers.origin ? { 'Access-Control-Allow-Origin': headers.origin, Vary: 'Origin',
    'Access-Control-Expose-Headers': 'X-ARGUS-OWNER-NONCE' } : {};
  return nonce ? { ...cors, 'X-ARGUS-OWNER-NONCE': nonce } : cors;
}

function fulfillCapturedSnapshot(route, evidence, delayMs) {
  const url = new URL(route.request().url());
  const key = `${url.searchParams.get('symbol')}:${url.searchParams.get('horizon')}`;
  const body = evidence.snapshotBodies.get(key);
  if (!body) return route.abort('failed');
  return new Promise((resolve) => setTimeout(resolve, delayMs))
    .then(() => route.fulfill({ status: 200, contentType: 'application/json', headers: controlledOwnerHeaders(route), body }));
}

async function waitForShell(page) {
  await owner.login(page);
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
  await page.waitForFunction(() => {
    const contract = document.querySelector(
      '[data-argus-contract="canonical-market-snapshot-v1"]',
    );
    return contract?.getAttribute('data-canonical-instrument') === '1321'
      && contract?.getAttribute('data-canonical-horizon') === '5D'
      && contract?.getAttribute('data-canonical-verification') === 'verified';
  }, null, { timeout });
}

async function verifyRetainedResearchMatrix(page, backendOrigin) {
  return page.evaluate(async ({ origin, symbols, horizons }) => {
    const rows = [];
    for (const symbol of symbols) for (const horizon of horizons) {
      const url = new URL('/api/argus/chart-intelligence', origin);
      url.searchParams.set('scope', 'market');
      url.searchParams.set('symbol', symbol);
      url.searchParams.set('horizon', horizon);
      url.searchParams.set('snapshot', 'verified');
      const response = await fetch(url, { cache: 'no-store' });
      const body = await response.json();
      const payload = body?.payload ?? body;
      rows.push({ symbol, horizon, status: response.status,
        snapshotId: body?.snapshotId ?? null,
        verification: body?.verificationStatus ?? null,
        instrument: payload?.instrument ?? payload?.symbol ?? symbol,
        automaticAiCalls: payload?.automaticAiCalls ?? null });
    }
    return rows;
  }, { origin: backendOrigin, symbols: SYMBOLS, horizons: HORIZONS });
}

async function geometry(page, viewport) {
  // Chromium does not expose iOS env() values, so record the native value and
  // separately prove the runtime guard rejects an oversized installed-web-view
  // value before exercising the exact 34px maximum accepted by the contract.
  const hostileGeometry = await page.evaluate(async () => {
    document.documentElement.style.setProperty('--argus-safe-bottom', '92px');
    const navHeightBeforeRefresh = document.querySelector('.nav')
      ?.getBoundingClientRect().height ?? null;
    window.dispatchEvent(new Event('pageshow'));
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const bounded = parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--argus-safe-bottom'));
    document.documentElement.style.setProperty('--argus-safe-bottom', '34px');
    return { boundedSafeAreaBottom: bounded, navHeightBeforeRefresh };
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
    const navControlsRect = rect('.nav__mobile');
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
      hostileSafeAreaBottom: size.hostileGeometry.boundedSafeAreaBottom,
      hostileNavHeightBeforeRefresh: size.hostileGeometry.navHeightBeforeRefresh,
      navRect, navControlsRect, stickyCommandRect,
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
      navTouchTargets: [...document.querySelectorAll('.nav__mobile > button, .nav__mobile > a, .nav__mobile > details > summary')]
        .map((element) => element.getBoundingClientRect().height),
    };
  }, { ...viewport, hostileGeometry });
}

async function navigationAudit(page, evidence) {
  const sequence = [
    ['Today', '#today'], ['Watchlist', '#holdings'], ['Settings', '#settings'],
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
  const thirteenM = page.locator('.nav__mobile').getByRole('link', { name: '13Mを開く', exact: true });
  if (await thirteenM.getAttribute('href') !== 'https://argus-13m-shadow.onrender.com/') {
    evidence.failures.push('13m-navigation-target');
  }
  const mobileOrder = await page.locator('.nav__mobile').locator('button, a').allTextContents();
  if (mobileOrder.join('|') !== 'Today|Watchlist|13M|Settings') {
    evidence.failures.push('13m-navigation-position');
  }
  await page.goBack(); await page.waitForFunction(() => location.hash === '#holdings');
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
  if (back !== 'Watchlist' || forward !== 'Settings') {
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
  let primaryFailure = null;
  try {
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
  await selectCanonical1321FiveDay(page);
  const otherMarkets = page.locator('[data-argus-contract="other-markets-actuals-v1"]');
  if (!await otherMarkets.evaluate((element) => element.open)) {
    await otherMarkets.locator('summary').click();
  }
  const selector = page.locator('[data-argus-control="market-instrument"]');
  await selector.first().waitFor({ state: 'attached', timeout: 30_000 });
  if (await selector.count() !== 4) evidence.failures.push('other-market-selector-not-four');
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
        const actuals = document.querySelector(
          '[data-argus-contract="other-market-actuals-explorer-v1"]');
        const selectedChart = actuals?.querySelector('[data-market-snapshot-id]');
        const contract = document.querySelector(
          '[data-argus-contract="canonical-market-snapshot-v1"]',
        );
        return actuals?.getAttribute('data-other-market-symbol') === expectedSymbol
          && actuals?.getAttribute('data-other-market-horizon') === expectedHorizon
          && Boolean(selectedChart?.getAttribute('data-market-snapshot-id'))
          && contract?.getAttribute('data-canonical-instrument') === '1321'
          && contract?.getAttribute('data-canonical-horizon') === '5D'
          && contract?.getAttribute('data-canonical-verification') === 'verified';
      }, { expectedSymbol: symbol, expectedHorizon: horizon }, { timeout: 30_000 });
      await waitForCanonicalProjectionContract(page);
      const record = await page.evaluate(({ expectedSymbol, expectedHorizon }) => ({
        symbol: document.querySelector('[data-argus-contract="other-market-actuals-explorer-v1"]')
          ?.getAttribute('data-other-market-symbol') ?? '',
        horizon: document.querySelector('[data-argus-contract="other-market-actuals-explorer-v1"]')
          ?.getAttribute('data-other-market-horizon') ?? '',
        selectedSnapshotId: document.querySelector(
          '[data-argus-contract="other-market-actuals-explorer-v1"] [data-market-snapshot-id]')
          ?.getAttribute('data-market-snapshot-id'),
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
      if (record.horizon !== horizon || !record.snapshotId || !record.selectedSnapshotId
          || record.verification !== 'verified'
          || record.symbol !== symbol
          || record.canonicalInstrument !== '1321'
          || record.canonicalHorizon !== '5D') {
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
      && Math.abs((audit.navVisualBottomGap ?? 99) - 40) > 1) {
      evidence.failures.push(`nav-visual-bottom-gap:${viewport.width}`);
    }
    if (!Number.isFinite(audit.hostileSafeAreaBottom)
      || audit.hostileSafeAreaBottom < 0 || audit.hostileSafeAreaBottom > 34) {
      evidence.failures.push(`safe-area-bound:${viewport.width}`);
    }
    if (viewport.width <= 720
      && (!Number.isFinite(audit.hostileNavHeightBeforeRefresh)
        || Math.abs(audit.hostileNavHeightBeforeRefresh - 86) > 1)) {
      evidence.failures.push(`hostile-nav-height:${viewport.width}`);
    }
    if (viewport.width <= 720
      && (Math.abs((audit.navRect?.height ?? 99) - 86) > 1
        || Math.abs((audit.navControlsRect?.height ?? 99) - 44) > 1)) {
      evidence.failures.push(`fixed-nav-height:${viewport.width}`);
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
            && document.querySelector('.at-canonical-load-status .triangle-step-loader')) {
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
  const coldLoaderAppeared = (async () => {
    // This wait starts before the page even navigates; the owner login it
    // waits behind includes the seven-second owner-wide throttle and, right
    // after a release, one self-healed second login (2026-09-30 release of
    // 13.7.80 failed here at 30s). Bound it by the login's own budget.
    if (owner.enabled) await coldPage.locator('.owner-access-bar > summary').waitFor({ state: 'visible', timeout: 90_000 });
    return coldPage.locator(
    '.at-canonical-load-status .triangle-step-loader',
  ).waitFor({ state: 'visible', timeout: 5_000 });
  })();
  // A detached wait must not turn into an unhandled rejection that hides the
  // primary failure (e.g. an owner login error) behind "page closed".
  coldLoaderAppeared.catch(() => {});
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
    '.at-canonical-load-status .triangle-step-loader').count();
  const skeletonHeight = await coldPage.locator('.at-canonical-load-status').evaluate(
    (element) => element.getBoundingClientRect().height);
  await screenshot(coldPage, 'today-cold-loader.png');
  if (!coldSemanticState.pass || loaderTiming.roundedDelayMs == null || before225
      || !after225 || skeletonHeight < 90) {
    evidence.failures.push('cold-loader-contract');
  }
  await owner.logout(coldPage);
  await cold.close();

  // A six-second cold delay must expose the explicit initial preparation label.
  const slow = await browser.newContext({
    viewport: { width: 430, height: 932 }, serviceWorkers: 'block',
  });
  await isolateChartReads(slow, evidence);
  await slow.route('**/api/argus/chart-intelligence?*',
    (route) => fulfillCapturedSnapshot(route, evidence, 6_000));
  const slowPage = await slow.newPage();
  const slowStateAppeared = (async () => {
    if (owner.enabled) await slowPage.locator('.owner-access-bar > summary').waitFor({ state: 'visible', timeout: 90_000 });
    return slowPage.waitForFunction(({ selector }) => {
    const nodes = [...document.querySelectorAll(selector)];
    if (nodes.length !== 1) return false;
    const node = nodes[0];
    const visibleStatus = document.querySelector('.at-canonical-load-status');
    if (node.getAttribute('data-projection-state') !== 'missing'
        || node.getAttribute('data-projection-snapshot-id')
        || node.getAttribute('data-projection-response-snapshot-id')
        || node.getAttribute('data-projection-snapshot-state') !== 'NO_CACHE_LOADING'
        || !visibleStatus?.textContent?.includes('日経平均の根拠を確認しています')) return false;
    return {
      state: 'missing',
      snapshotState: 'NO_CACHE_LOADING',
      label: '日経平均の根拠を確認しています',
    };
  }, { selector: CANONICAL_PROJECTION_STATE_SELECTOR }, { timeout: 7_000 });
  })();
  slowStateAppeared.catch(() => {});
  await slowPage.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(slowPage);
  await openCanonicalEvidence(slowPage);
  const slowState = await slowStateAppeared.then((handle) => handle.jsonValue());
  const slowLabel = slowState?.label ?? null;
  if (slowState?.state !== 'missing'
      || slowState?.label !== '日経平均の根拠を確認しています') {
    evidence.failures.push('slow-label');
  }
  await owner.logout(slowPage);
  await slow.close();

  // A failed cold request terminates the loader and leaves an actionable retry.
  const failure = await browser.newContext({
    viewport: { width: 430, height: 932 }, serviceWorkers: 'block',
  });
  await isolateChartReads(failure, evidence);
  await failure.route('**/api/argus/chart-intelligence?*',
    (route) => route.fulfill({ status: 500, contentType: 'application/json', headers: controlledOwnerHeaders(route),
      body: '{"error":"controlled"}' }));
  const failurePage = await failure.newPage();
  await failurePage.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(failurePage);
  await openCanonicalEvidence(failurePage);
  await failurePage.locator('.at-canonical-load-status')
    .getByRole('button', { name: '再取得' })
    .waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {});
  const failureState = {
    loader: await failurePage.locator('.at-canonical-load-status .triangle-step-loader').count(),
    retry: await failurePage.locator('.at-canonical-load-status')
      .getByRole('button', { name: '再取得' }).count(),
  };
  if (failureState.loader || !failureState.retry) evidence.failures.push('failure-loader-contract');
  await owner.logout(failurePage);
  await failure.close();

  // Warm cache is the immediate visible authority while a controlled network
  // request revalidates in the background. Presentation loaders are optional;
  // this gate observes semantic state and exact snapshot identity only.
  // IndexedDB remains intact across seed and reload within this context.
  await page.setViewportSize({ width: 430, height: 932 });
  // The main page's session was issued first; the isolated contexts above
  // each sign in again, and the server keeps a bounded number of concurrent
  // sessions, evicting the earliest. The product then correctly returns to
  // the lock screen (2026-10-01: locked, route #settings). The owner signs in
  // again in that case; so does this reader, and says so in the log.
  if (owner.enabled && await page.locator('.owner-access-screen').count()) {
    console.log('mobile-today-acceptance: main page session was evicted; signing in again');
    await owner.login(page);
  }
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
  await owner.logout(warmPage);
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
    (route) => route.fulfill({ status: 304, headers: controlledOwnerHeaders(route), body: '' }));
  await owner.logout(warmPage);
  await warmPage.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(warmPage); await waitForTodayChart(warmPage);
  const after304 = await warmPage.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .getAttribute('data-canonical-snapshot-id');
  await warm.unroute('**/api/argus/chart-intelligence?*');
  if (!warmSeedSnapshotId || before304 !== warmSeedSnapshotId
      || after304 !== before304) {
    evidence.failures.push('not-modified-continuity');
  }
  await owner.logout(warmPage);
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
      headers: { ...controlledOwnerHeaders(route), 'Retry-After': '2' },
      body: '{"error":"rate_limited","message":"controlled acceptance limit"}',
    });
  });
  await owner.logout(rateLimitPage);
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
  await owner.logout(rateLimitPage);
  await rateLimitContext.close();

  // M13 retains device data in both modes. Owner mode must lock offline,
  // then prove the same identity only after a fresh online UI ceremony.
  await drainResponseTasks(evidence);
  await owner.logout(page);
  const preservedBefore = owner.enabled ? await verifiedStoreFingerprint(page) : null;
  await context.setOffline(true);
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  let offlineSnapshotId;
  let preservedOffline = null;
  if (owner.enabled) {
    await owner.locked(page);
    preservedOffline = await verifiedStoreFingerprint(page);
    if (!preservedBefore?.records || JSON.stringify(preservedBefore) !== JSON.stringify(preservedOffline)) {
      evidence.failures.push('offline-snapshot-continuity');
    }
    await screenshot(page, 'today-offline-locked.png');
    await context.setOffline(false);
    await waitForShell(page);
    await waitForTodayChart(page);
    offlineSnapshotId = await page.locator(CANONICAL_SNAPSHOT_SELECTOR).getAttribute('data-canonical-snapshot-id');
  } else {
    await waitForShell(page);
    await waitForTodayChart(page);
    offlineSnapshotId = await page.locator(CANONICAL_SNAPSHOT_SELECTOR).getAttribute('data-canonical-snapshot-id');
    await screenshot(page, 'today-offline-cached.png');
    await context.setOffline(false);
  }
  if (!onlineSnapshotId || offlineSnapshotId !== onlineSnapshotId) {
    evidence.failures.push('offline-snapshot-continuity');
  }

  // M15 — headline-first decision visibility: with the verified Nikkei
  // snapshot held open, ARGUS's editorial view and canonical decision remain
  // readable. The retired four-market probability panel must not reappear.
  let releaseHeavyHold;
  const heavyHold = new Promise((resolve) => { releaseHeavyHold = resolve; });
  const headlineContext = await browser.newContext({
    viewport: { width: 430, height: 932 }, serviceWorkers: 'block',
  });
  let heldHeavyRequests = 0;
  await headlineContext.route('**/api/argus/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/argus/today-headline') return route.continue();
    if (owner.enabled && isOwnerCeremony(url.href, BACKEND_ORIGIN, route.request().method())) return route.continue();
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
    await waitForContractState(headlinePage, 'headline-first-decision-visibility',
      () => {
        const selectors = document.querySelectorAll(
          '[data-argus-control="market-instrument"]');
        const projection = document.querySelector(
          '[data-argus-contract="today-projection-state-v1"]');
        const probabilityRow = document.querySelector('.at-proj-prob');
        const editorial = document.querySelector('.at-view-hero .at-brief');
        const decision = document.querySelector('.at-decision');
        const loader = document.querySelector('.at-canonical-load-status .triangle-step-loader');
        const primary = document.querySelector('.at-call strong');
        return selectors.length === 0
          && projection?.getAttribute('data-projection-state') === 'missing'
          && !probabilityRow
          && !!editorial && !!decision && !!loader
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
  await owner.logout(headlinePage);
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
    offline: { onlineSnapshotId, offlineSnapshotId, before304, after304, ownerLocked: owner.enabled, preservedBefore, preservedOffline },
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
  // The detailed list is in the sealed artifact; the log names up to ten
  // unexpected console errors (type, path without query, redacted and
  // reduced text) so a console-errors failure is actionable from the run.
  for (const item of consoleClassification.unexpected.slice(0, 10)) {
    let where = '';
    try { where = item.location ? new URL(item.location).pathname : ''; } catch { where = 'unparsed'; }
    const text = owner.redact(String(item.message ?? '')).replace(/[^A-Za-z0-9 :._/()-]/g, '').slice(0, 160);
    console.error(`mobile-today-acceptance console-error: ${item.type} ${where} ${text}`);
  }
  await owner.logout(page);
  await context.close();
  await owner.scan(OUT_DIR);
  if (owner.enabled) await writeJson('owner-artifacts-safe.json', { verified: true });
  if (evidence.failures.length) {
    throw new Error(`mobile Today acceptance failed: ${result.failures.join(', ')}`);
  }
  console.log(`mobile-today-acceptance: PASS (${evidence.combinations.length} combinations)`);
  } catch (error) {
    primaryFailure = error;
    // One line per open page with fixed tokens, so a release failure names
    // the page state (lock screen, route, shell, Today, snapshot state)
    // instead of needing another diagnostic release per failing step.
    const states = [];
    for (const [contextIndex, remaining] of browser.contexts().entries()) {
      for (const [pageIndex, tab] of remaining.pages().entries()) {
        const state = await tab.evaluate(() => [
          `locked=${document.querySelector('.owner-access-screen') ? 'yes' : 'no'}`,
          `lock=${(document.documentElement.dataset.argusOwnerLock || 'none').replace(/[/]/g, '_').replace(/[^A-Za-z0-9_-]/g, '-').slice(0, 90)}`,
          `route=${(location.hash || '#').slice(0, 24)}`,
          `header=${document.querySelector('.shell__header') ? 'yes' : 'no'}`,
          `nav=${document.querySelector('.nav__mobile') ? 'yes' : 'no'}`,
          `today=${document.querySelector('.argus-today') ? 'yes' : 'no'}`,
          `snapshot=${document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')?.getAttribute('data-canonical-snapshot-state') || 'none'}`,
          `code=${document.querySelector('[role="status"][data-owner-code]')?.getAttribute('data-owner-code') || 'none'}`,
          `hidden=${document.hidden ? 'yes' : 'no'}`,
        ].join(',').replace(/[^A-Za-z0-9_,=#-]/g, '')).catch(() => 'unreadable');
        states.push(`c${contextIndex}p${pageIndex}:${state}`);
      }
    }
    // Printed directly: the fatal handler prints error.stack, which V8 fixes
    // at construction, so an appended message would never reach the log.
    if (states.length) console.error(`mobile-today-acceptance pages: ${states.join(' ; ')}`);
    throw error;
  } finally {
    const cleanupFailures = [];
    try {
      for (const remaining of browser.contexts()) for (const tab of remaining.pages()) {
        try { await owner.logout(tab); } catch { cleanupFailures.push('owner_logout_failed'); }
      }
    } finally { await browser.close(); }
    if (cleanupFailures.length) {
      await writeJson('cleanup-failure.json', { failures: cleanupFailures });
      if (!primaryFailure) throw new Error('owner_cleanup_failed');
    }
  }
}

run().catch(async (error) => {
  const message = sanitize(error instanceof Error ? error.stack : error);
  try {
    await writeJson('fatal.json', { testedAt: new Date().toISOString(), error: message });
  } catch { /* preserve original failure */ }
  console.error(message);
  process.exit(1);
});
