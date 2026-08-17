import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const PUBLIC_URL = process.env.ARGUS_PUBLIC_URL
  || 'http://127.0.0.1:4173/argus/';
const EXPECTED_VERSION = process.env.ARGUS_EXPECTED_VERSION || '';
const EXPECTED_SHA = process.env.ARGUS_EXPECTED_SHA || '';
const OUT_DIR = path.resolve(process.env.ARGUS_MOBILE_ACCEPTANCE_OUT
  || '/tmp/argus-mobile-today-acceptance');
const TODAY_URL = `${PUBLIC_URL.replace(/\/?$/, '/')}#today`;
const SYMBOLS = ['1321', '1306', 'SPY', 'QQQ'];
const HORIZONS = ['1D', '5D', '20D'];
const CANONICAL_SNAPSHOT_SELECTOR =
  '[data-argus-contract="canonical-market-snapshot-v1"]'
  + '[data-canonical-verification="verified"]'
  + '[data-canonical-snapshot-id]';
const LOADER_THRESHOLD_MS = 225;
const LOADER_TIMING_TOLERANCE_MS = 1;
const WARM_LOADER_DEADLINE_MS = 2_000;
const COMBINATION_PACE_MS = 1_000;
const VIEWPORTS = [
  { width: 320, height: 568 }, { width: 375, height: 812 },
  { width: 390, height: 844 }, { width: 393, height: 852 },
  { width: 414, height: 896 }, { width: 430, height: 932 },
  { width: 932, height: 430 },
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
  for (const error of evidence.consoleErrors) {
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
  return { unexpected, expected429 };
}

async function writeJson(name, value) {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(path.join(OUT_DIR, name), `${JSON.stringify(value, null, 2)}\n`);
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
    if (request.method() === 'POST' && /argus-backend-.*\.onrender\.com$/.test(url.hostname)) {
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
  const projection = page.locator('.at-projection');
  if (!await projection.isVisible()) {
    await page.getByText('根拠・市場データ・システム情報', { exact: true }).click();
  }
  await projection.waitFor({ state: 'visible', timeout });
}

async function geometry(page, viewport) {
  // Chromium does not expose iOS env() values, so record the native value and
  // separately exercise the exact 34px maximum accepted by the CSS contract.
  await page.evaluate(() => {
    document.documentElement.style.setProperty('--argus-safe-bottom', '34px');
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
    return {
      viewport: size,
      innerHeight, outerHeight,
      clientHeight: document.documentElement.clientHeight,
      visualViewportHeight: vv?.height ?? null,
      visualViewportOffsetTop: vv?.offsetTop ?? null,
      visualViewportWidth: vv?.width ?? null,
      nativeSafeAreaBottom,
      exercisedSafeAreaBottom: 34,
      navRect, stickyCommandRect,
      shellRect: rect('.shell'), bodyRect: rect('body'),
      mainRect: rect('.shell__main'),
      visualViewportBottom,
      distanceFromViewportBottom: navRect
        ? Math.abs(visualViewportBottom - navRect.bottom) : null,
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
  }, viewport);
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
  const selector = page.locator('.at-index-strip button');
  await selector.first().waitFor({ state: 'visible', timeout: 30_000 });
  if (await selector.count() !== 4) evidence.failures.push('today-selector-not-four');
  await waitForTodayChart(page);
  const initialChartRequests = evidence.network.slice(initialRequestsAt)
    .filter((row) => row.pathname === '/api/argus/chart-intelligence');
  const initialKeys = new Set(initialChartRequests.map(
    (row) => `${row.symbol}:${row.horizon}:${row.snapshot}:${row.scope}`));
  for (const symbol of SYMBOLS) {
    await selector.filter({ hasText: symbol === '1321' ? '日経'
      : symbol === '1306' ? 'TOPIX' : symbol === 'SPY' ? 'S&P' : 'NASDAQ' }).click();
    for (const horizon of HORIZONS) {
      await page.getByRole('group', { name: '予測期間' })
        .getByRole('button', { name: horizon, exact: true }).click();
      await waitForTodayChart(page);
      const record = await page.evaluate(({ expectedSymbol, expectedHorizon }) => ({
        symbol: document.querySelector('.at-proj-heading b')?.textContent ?? '',
        horizon: document.querySelector('.at-horizon button[aria-pressed="true"]')?.textContent ?? '',
        snapshotId: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-snapshot-id'),
        snapshotState: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-snapshot-state'),
        verification: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-verification'),
        canonicalInstrument: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-instrument'),
        canonicalHorizon: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
          ?.getAttribute('data-canonical-horizon'),
        expectedSymbol, expectedHorizon,
      }), { expectedSymbol: symbol, expectedHorizon: horizon });
      evidence.combinations.push(record);
      if (!record.symbol.includes(symbol) || record.horizon !== horizon || !record.snapshotId
          || record.verification !== 'verified'
          || record.canonicalInstrument !== symbol
          || record.canonicalHorizon !== horizon) {
        evidence.failures.push(`today-combination:${symbol}:${horizon}`);
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
    if (audit.horizontalOverflow) evidence.failures.push(`horizontal-overflow:${viewport.width}`);
    if (viewport.width <= 720 && audit.navTouchTargets.some((height) => height < 44)) {
      evidence.failures.push(`touch-target:${viewport.width}`);
    }
  }
  await page.setViewportSize({ width: 430, height: 932 });
  await screenshot(page, 'iphone-14-pro-max-full.png', true);
  await screenshot(page, 'iphone-14-pro-max-bottom-nav.png');
  const navigation = await navigationAudit(page, evidence);

  // Cold Today: no IndexedDB/SW, 2s network delay. The chart footprint remains
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
    (route) => fulfillCapturedSnapshot(route, evidence, 2_000));
  const coldPage = await cold.newPage();
  await coldPage.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(coldPage);
  await coldPage.locator('.at-projection-missing .triangle-step-loader')
    .waitFor({ state: 'visible', timeout: 2_000 });
  const loaderTiming = await coldPage.evaluate(() => {
    const entries = performance.getEntriesByName(
      'argus-snapshot:network-revalidation-start');
    const networkStart = entries.length ? entries[entries.length - 1].startTime : null;
    const firstLoaderAt = globalThis.__ARGUS_LOADER_FIRST_AT__;
    return {
      networkStart,
      firstLoaderAt,
      rawDelayMs: networkStart != null && firstLoaderAt != null
        ? firstLoaderAt - networkStart : null,
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
  if (loaderTiming.roundedDelayMs == null || before225
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
  await slowPage.goto(TODAY_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(slowPage);
  await slowPage.waitForTimeout(5_300);
  const slowLabel = await slowPage.locator('.at-projection-missing').innerText();
  if (!slowLabel.includes('初回データを準備中')) evidence.failures.push('slow-label');
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

  // Warm cache + delayed revalidation keeps the chart and shows only the
  // compact loader. Use a dedicated SW-blocked context so the test controls
  // the network revalidation precondition instead of allowing a fresh service
  // worker response to bypass Playwright routing. IndexedDB remains intact
  // across the seed and reload within this context.
  await page.setViewportSize({ width: 430, height: 932 });
  await page.locator('.nav__mobile').getByRole('button', { name: 'Today', exact: true }).click();
  await waitForTodayChart(page);
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
  await waitForTodayChart(warmPage);
  const warmSeedSnapshotId = await warmPage.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .getAttribute('data-canonical-snapshot-id');
  await warm.unroute('**/api/argus/chart-intelligence?*');
  let resolveWarmRequestStart;
  const warmRequestStart = new Promise((resolve) => {
    resolveWarmRequestStart = resolve;
  });
  await warm.route('**/api/argus/chart-intelligence?*', (route) => {
    resolveWarmRequestStart?.(Date.now());
    resolveWarmRequestStart = null;
    return fulfillCapturedSnapshot(route, evidence, 6_000);
  });
  await warmPage.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  await waitForShell(warmPage);
  await waitForTodayChart(warmPage);
  const warmStartedAt = await Promise.race([
    warmRequestStart,
    new Promise((_, reject) => setTimeout(
      () => reject(new Error('controlled warm revalidation did not start')),
      5_000)),
  ]);
  const warmLoaderLocator = warmPage.locator(
    '.at-chart-status .triangle-step-loader');
  let warmLoaderAppearedAt = null;
  await warmLoaderLocator.waitFor({
    state: 'visible', timeout: WARM_LOADER_DEADLINE_MS,
  }).then(() => { warmLoaderAppearedAt = Date.now(); }).catch(() => {});
  const warmLoaderDelayMs = warmLoaderAppearedAt == null
    ? null : warmLoaderAppearedAt - warmStartedAt;
  const warmLoader = await warmLoaderLocator.count();
  const warmSkeleton = await warmPage.locator('.at-projection-missing').count();
  await screenshot(warmPage, 'today-warm-revalidation-loader.png');
  await warmPage.waitForTimeout(Math.max(0, 6_200 - (Date.now() - warmStartedAt)));
  await warm.unroute('**/api/argus/chart-intelligence?*');
  if (!warmLoader || warmSkeleton || warmLoaderDelayMs == null
      || warmLoaderDelayMs < LOADER_THRESHOLD_MS - LOADER_TIMING_TOLERANCE_MS
      || warmLoaderDelayMs > WARM_LOADER_DEADLINE_MS) {
    evidence.failures.push('warm-loader-contract');
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
  await waitForShell(rateLimitPage); await waitForTodayChart(rateLimitPage);
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
  await rateLimitPage.waitForTimeout(1_000);
  await rateLimitContext.unroute('**/api/argus/chart-intelligence?*');
  const controlledRateLimit = {
    calls: controlled429Calls,
    expectedCalls: initialKeys.size,
    retryAfterSeconds: 2,
    seedSnapshotId: rateLimitSeedSnapshotId,
    cachedSnapshotId: rateLimitedSnapshotId,
  };
  if (controlled429Calls !== initialKeys.size
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
      warmLoader, warmSkeleton, warmLoaderDelayMs, loaderTiming,
    },
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
