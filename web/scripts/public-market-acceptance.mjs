import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const PUBLIC_URL = process.env.ARGUS_PUBLIC_URL || 'https://mitsugue.github.io/argus/';
const EXPECTED_VERSION = process.env.ARGUS_EXPECTED_VERSION || '';
const EXPECTED_SHA = process.env.ARGUS_EXPECTED_SHA || '';
const EXPECTED_BACKEND_VERSION = process.env.ARGUS_EXPECTED_BACKEND_VERSION || '';
const EXPECTED_BACKEND_SHA = process.env.ARGUS_EXPECTED_BACKEND_SHA || '';
const MODE = process.env.ARGUS_ACCEPTANCE_MODE || 'accept';
const OUT_DIR = path.resolve(process.env.ARGUS_ACCEPTANCE_OUT || '../artifacts/market-public-acceptance');
const PROFILE_DIR = path.resolve(process.env.ARGUS_WARM_PROFILE_DIR || '../artifacts/market-warm-profile');
const CACHE_BUSTED_URL = `${PUBLIC_URL}?release=${encodeURIComponent(EXPECTED_VERSION)}&sha=${encodeURIComponent(EXPECTED_SHA.slice(0, 7))}#market`;
const NORMAL_URL = `${PUBLIC_URL.replace(/\/?$/, '/')}#market`;
const DATA_TIMEOUT_MS = 5_000;
const PAGE_TIMEOUT_MS = 25_000;
const BACKEND_READY_TIMEOUT_MS = 8 * 60_000;
const MARKET_CACHE_READY_TIMEOUT_MS = 30 * 60_000;
const BACKEND_IDENTITY_URL =
  'https://argus-backend-3j2m.onrender.com/api/argus/data-quality';
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 430, height: 932 },
  { width: 390, height: 844 },
];
const TABS = ['OVERVIEW', 'REPLAY', 'LEDGER'];
const INSTRUMENTS = ['1321', '1306', 'SPY', 'QQQ'];
const HORIZONS = ['1D', '5D', '20D'];

const isBlack = (value) => ['rgb(0, 0, 0)', 'rgba(0, 0, 0, 1)', '#000', '#000000', 'black']
  .includes(String(value || '').trim().toLowerCase());
const sanitize = (value) => String(value || '')
  .replace(/([?&](?:token|key|authorization|auth)=[^&\s]+)/gi, '?redacted')
  .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
  .slice(0, 1000);

async function writeJson(name, value) {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(path.join(OUT_DIR, name), `${JSON.stringify(value, null, 2)}\n`);
}

async function captureScreenshot(page, evidence, filename, label) {
  try {
    await page.screenshot({
      path: path.join(OUT_DIR, 'screenshots', filename),
      fullPage: false,
      animations: 'disabled',
      timeout: 10_000,
    });
    return true;
  } catch (error) {
    const errorClass = error instanceof Error ? error.name : 'ScreenshotError';
    evidence.failures.push(`screenshot:${label}:${errorClass}`);
    return false;
  }
}

async function seedWarmProfile() {
  await fs.rm(PROFILE_DIR, { recursive: true, force: true });
  await fs.mkdir(PROFILE_DIR, { recursive: true });
  const context = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: true,
    viewport: { width: 1280, height: 800 },
  });
  const page = context.pages()[0] || await context.newPage();
  await page.goto(NORMAL_URL, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS });
  await page.waitForSelector('text=A.R.G.U.S.', { timeout: PAGE_TIMEOUT_MS });
  // Warm the actual Market GET path, not just the shell/PWA files. This remains
  // outside formal timing: mainAcceptance still enforces the 5-second gate.
  await waitForData(page, 30_000);
  const evidence = await page.evaluate(async () => ({
    frontendVersion: globalThis.__ARGUS_VERSION__ || null,
    frontendBuildSha: globalThis.__ARGUS_BUILD_SHA__ || null,
    serviceWorkerCount: (await navigator.serviceWorker.getRegistrations()).length,
    cacheNames: await caches.keys(),
    url: location.href,
  }));
  await context.close();
  await fs.writeFile(path.join(PROFILE_DIR, 'predeploy-version.json'),
    `${JSON.stringify({ ...evidence, seededAt: new Date().toISOString() }, null, 2)}\n`);
  return evidence;
}

function attachEvidence(page, evidence) {
  page.on('console', (message) => {
    if (message.type() === 'error') {
      evidence.consoleErrors.push({ type: 'console.error', message: sanitize(message.text()) });
    } else if (message.type() === 'warning' && /react/i.test(message.text())) {
      evidence.reactWarnings.push({ type: 'console.warning', message: sanitize(message.text()) });
    }
  });
  page.on('pageerror', (error) => {
    evidence.consoleErrors.push({ type: 'pageerror', message: sanitize(error.message) });
  });
  page.on('request', (request) => {
    const parsed = new URL(request.url());
    const row = {
      method: request.method(),
      origin: parsed.origin,
      pathname: parsed.pathname,
      resourceType: request.resourceType(),
    };
    evidence.network.push(row);
    if (request.method() === 'POST' && /argus-backend-.*\.onrender\.com$/.test(parsed.hostname)) {
      evidence.aiPostCount += 1;
    }
  });
  page.on('response', async (response) => {
    const parsed = new URL(response.url());
    const match = parsed.pathname === '/api/argus/chart-intelligence';
    if (!match || response.status() !== 200) return;
    try {
      const body = await response.json();
      const view = body.payload || body;
      const symbol = String(body.instrument || view.symbol
        || parsed.searchParams.get('symbol') || '');
      const requestedHorizon = String(body.horizon
        || parsed.searchParams.get('horizon') || '').replace(/D$/i, '');
      const contexts = view.marketReplay?.contexts || {};
      const prior = evidence.marketData[symbol] || {};
      evidence.marketData[symbol] = {
        cacheStatus: view.marketReplay?.cacheStatus || prior.cacheStatus || null,
        methodVersion: view.marketReplay?.methodVersion || prior.methodVersion || null,
        stateHash: view.marketReplay?.stateHash || prior.stateHash || null,
        automaticAiCalls: view.automaticAiCalls
          ?? view.marketReplay?.automaticAiCalls ?? prior.automaticAiCalls ?? null,
        snapshotIds: {
          ...(prior.snapshotIds || {}),
          ...(requestedHorizon && body.snapshotId
            ? { [requestedHorizon]: body.snapshotId } : {}),
        },
        contexts: Object.fromEntries(Object.entries(contexts).map(([key, value]) => [
          key,
          {
            datasetHash: value?.datasetHash || null,
            methodVersion: value?.methodVersion || null,
            maeQ90: value?.outcomeDistributions?.mae?.q90 ?? null,
            maeMedian: value?.outcomeDistributions?.mae?.median ?? null,
          },
        ])),
      };
    } catch (error) {
      evidence.consoleErrors.push({
        type: 'acceptance-parser',
        message: sanitize(error instanceof Error
          ? error.message : 'chart-intelligence response was not valid JSON'),
      });
    }
  });
}

async function waitForVersion(page, version, timeout = PAGE_TIMEOUT_MS) {
  await page.waitForFunction((expected) =>
    globalThis.__ARGUS_VERSION__ === expected
    && document.body?.innerText.includes(`v${expected}`), version, { timeout });
}

async function waitForMarket(page) {
  const marker = page.getByText('MARKET CONTEXT REPLAY', { exact: true });
  if (!await marker.isVisible().catch(() => false)) {
    await page.getByRole('button', { name: 'Market Context', exact: true }).click();
  }
  await marker.waitFor({ state: 'visible', timeout: PAGE_TIMEOUT_MS });
}

async function waitForData(page, timeout = DATA_TIMEOUT_MS) {
  const started = Date.now();
  await page.waitForFunction(() => {
    const text = document.body?.innerText || '';
    return text.includes('AI POST 0')
      && !text.includes('no dataset hash')
      && !text.includes('replay cache pending')
      && !text.includes('キャッシュ取得中');
  }, null, { timeout });
  return Date.now() - started;
}

async function waitForBackendIdentity(request) {
  const deadline = Date.now() + BACKEND_READY_TIMEOUT_MS;
  let last = 'no_response';
  while (Date.now() < deadline) {
    try {
      const response = await request.get(BACKEND_IDENTITY_URL, {
        timeout: PAGE_TIMEOUT_MS,
        headers: { Accept: 'application/json' },
      });
      if (response.ok()) {
        const body = await response.json();
        const identity = body.buildIdentity || {};
        const versionMatches = !EXPECTED_BACKEND_VERSION
          || (identity.backendVersion || identity.appVersion) === EXPECTED_BACKEND_VERSION;
        const shaMatches = !EXPECTED_BACKEND_SHA
          || identity.backendBuildSha === EXPECTED_BACKEND_SHA
          || String(EXPECTED_BACKEND_SHA).startsWith(String(identity.backendBuildSha || ''));
        if (versionMatches && shaMatches) return { body, identity };
        last = `identity:${identity.backendVersion || identity.appVersion || 'unknown'}:`
          + `${identity.backendBuildSha || 'unknown'}`;
      } else {
        last = `http_${response.status()}`;
      }
    } catch (error) {
      last = error instanceof Error ? error.name : 'request_error';
    }
    await new Promise((resolve) => setTimeout(resolve, 10_000));
  }
  throw new Error(`backend identity did not become ready (${last})`);
}

async function waitForMarketCache(request) {
  // A new backend process is cache-only by contract. Give the independent
  // 30-minute natural scheduler one bounded window to publish all instruments.
  const deadline = Date.now() + MARKET_CACHE_READY_TIMEOUT_MS;
  let last = 'no_response';
  while (Date.now() < deadline) {
    try {
      const states = await Promise.all(INSTRUMENTS.map(async (symbol) => {
        const market = ['1321', '1306'].includes(symbol) ? 'JP' : 'US';
        const url = new URL('/api/argus/chart-intelligence',
          'https://argus-backend-3j2m.onrender.com');
        url.searchParams.set('scope', 'market');
        url.searchParams.set('timeframe', 'daily');
        url.searchParams.set('symbol', symbol);
        url.searchParams.set('market', market);
        const response = await request.get(url.toString(), {
          timeout: PAGE_TIMEOUT_MS,
          headers: { Accept: 'application/json' },
        });
        if (!response.ok()) return `${symbol}:http_${response.status()}`;
        const body = await response.json();
        const contexts = body.marketReplay?.contexts || {};
        const ready = body.marketReplay?.cacheStatus === 'hit'
          && body.automaticAiCalls === 0
          && HORIZONS.every((horizon) =>
            Boolean(contexts[horizon.replace('D', '')]?.datasetHash));
        return ready ? `${symbol}:ready` : `${symbol}:cache_not_ready`;
      }));
      if (states.every((state) => state.endsWith(':ready'))) return states;
      last = states.join(',');
    } catch (error) {
      last = error instanceof Error ? error.name : 'request_error';
    }
    await new Promise((resolve) => setTimeout(resolve, 10_000));
  }
  throw new Error(`market cache did not become ready (${last})`);
}

async function styleAudit(page) {
  return page.evaluate(() => {
    const black = new Set(['rgb(0, 0, 0)', 'rgba(0, 0, 0, 1)']);
    const transparent = new Set(['rgba(0, 0, 0, 0)', 'transparent']);
    const visible = (element) => {
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };
    const style = (selector, property) => {
      const element = [...document.querySelectorAll(selector)].find(visible);
      return element ? getComputedStyle(element)[property] : null;
    };
    const resolvedBackground = (selector) => {
      let element = [...document.querySelectorAll(selector)].find(visible);
      while (element) {
        const color = getComputedStyle(element).backgroundColor;
        if (color && !transparent.has(color)) return color;
        element = element.parentElement;
      }
      return getComputedStyle(document.body).backgroundColor;
    };
    const rgb = (value) => {
      const match = String(value || '').match(/rgba?\(([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/);
      return match ? match.slice(1, 4).map(Number) : null;
    };
    const luminance = (value) => {
      const channels = rgb(value);
      if (!channels) return null;
      const linear = channels.map((channel) => {
        const normalized = channel / 255;
        return normalized <= .03928 ? normalized / 12.92
          : ((normalized + .055) / 1.055) ** 2.4;
      });
      return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2];
    };
    const contrast = (left, right) => {
      const a = luminance(left);
      const b = luminance(right);
      if (a == null || b == null) return null;
      return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    };
    const svgElements = [...document.querySelectorAll('.market-replay svg *')]
      .filter((element) => !['g', 'defs', 'marker', 'title'].includes(element.tagName.toLowerCase()))
      .filter(visible);
    const blackFallbackCount = svgElements.filter((element) => {
      const computed = getComputedStyle(element);
      return black.has(computed.fill) || black.has(computed.stroke);
    }).length;
    const background = resolvedBackground('.market-replay');
    const chartBackground = resolvedBackground('.mr-chart');
    const distributionBackground = resolvedBackground('.mr-dist');
    const calibrationBackground = resolvedBackground('.mr-calibration');
    const histogramFill = style('.mr-dist rect', 'fill');
    const calibrationFill = style('.mr-calibration circle', 'fill');
    const volumeFill = style('.mr-volume', 'fill');
    const chipText = style('.mr-price-chip text', 'fill');
    const chipBackground = style('.mr-price-chip rect', 'fill');
    const axisText = style('.mr-chart text, .mr-calibration text', 'fill');
    const labels = [...document.querySelectorAll('.mr-dist-labels')]
      .filter(visible).map((element) => getComputedStyle(element).color);
    const tooltipTitles = [...document.querySelectorAll(
      '.mr-dist rect title, .mr-calibration circle title, .mr-volume title')]
      .map((element) => element.textContent?.trim() || '').filter(Boolean);
    return {
      histogramFill, calibrationFill, volumeFill, chipText, chipBackground,
      axisText, distributionLabelColors: labels, background,
      chartBackground, distributionBackground, calibrationBackground,
      histogramContrast: contrast(histogramFill, distributionBackground),
      calibrationContrast: contrast(calibrationFill, calibrationBackground),
      volumeContrast: contrast(volumeFill, chartBackground),
      priceChipContrast: contrast(chipText, chipBackground),
      axisContrast: contrast(axisText, chartBackground),
      distributionLabelContrasts: labels.map(
        (value) => contrast(value, distributionBackground)),
      blackFallbackCount,
      horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - innerWidth),
      chartDataEmpty: !document.querySelector(
        '.mr-chart, .mr-event-study svg, .mr-dist svg, .mr-ledger-grid, .mr-us-ledger'),
      tooltipCount: tooltipTitles.length,
    };
  });
}

function validateStyles(audit, failures, label, tab) {
  for (const [name, value] of [
    ['histogramFill', audit.histogramFill],
    ['calibrationFill', audit.calibrationFill],
    ['volumeFill', audit.volumeFill],
    ['chipText', audit.chipText],
    ['axisText', audit.axisText],
  ]) {
    if (value && isBlack(value)) failures.push(`${label}:${name}:black`);
  }
  if (audit.chipBackground && ['rgba(0, 0, 0, 0)', 'transparent'].includes(audit.chipBackground)) {
    failures.push(`${label}:price-chip:transparent`);
  }
  if (audit.blackFallbackCount) failures.push(`${label}:black-fallback:${audit.blackFallbackCount}`);
  if (audit.horizontalOverflow) failures.push(`${label}:horizontal-overflow:${audit.horizontalOverflow}`);
  if (audit.chartDataEmpty) failures.push(`${label}:chart-data-empty`);
  if (tab === 'OVERVIEW') {
    for (const [name, value, threshold] of [
      ['volume', audit.volumeContrast, 3],
      ['price-chip', audit.priceChipContrast, 4.5],
      ['axis', audit.axisContrast, 4.5],
    ]) {
      if (value == null || value < threshold) failures.push(`${label}:${name}-contrast-${value}`);
    }
  }
  if (tab === 'REPLAY') {
    for (const [name, value] of [
      ['histogram', audit.histogramContrast],
      ['calibration', audit.calibrationContrast],
    ]) {
      if (value == null || value < 3) failures.push(`${label}:${name}-contrast-${value}`);
    }
    if (audit.distributionLabelContrasts.length < 3
        || audit.distributionLabelContrasts.some((value) => value == null || value < 4.5)) {
      failures.push(`${label}:distribution-label-contrast`);
    }
    if (!audit.tooltipCount) failures.push(`${label}:tooltip-missing`);
  }
}

async function recordCombination(page, evidence, backend, viewport, tab, instrument, horizon,
                                 dataLoadMs) {
  const audit = await styleAudit(page);
  const horizonNumber = horizon.replace('D', '');
  const market = evidence.marketData[instrument] || {};
  const context = market.contexts?.[horizonNumber] || {};
  const renderedSnapshotId = await page.locator(
    '.market-replay[data-snapshot-id]').getAttribute('data-snapshot-id');
  const record = {
    publicUrl: page.url(),
    testedAt: new Date().toISOString(),
    frontendVersion: await page.evaluate(() => globalThis.__ARGUS_VERSION__ || null),
    frontendSha: await page.evaluate(() => globalThis.__ARGUS_BUILD_SHA__ || null),
    backendVersion: backend.backendVersion || backend.appVersion || null,
    backendSha: backend.backendBuildSha || null,
    viewport,
    tab,
    instrument,
    horizon,
    dataLoaded: !audit.chartDataEmpty,
    dataLoadMs,
    cacheStatus: market.cacheStatus || null,
    datasetHash: context.datasetHash || null,
    snapshotId: renderedSnapshotId,
    responseSnapshotId: market.snapshotIds?.[horizonNumber] || null,
    replayMethodVersion: context.methodVersion || market.methodVersion || null,
    maeQ90: context.maeQ90 ?? null,
    maeMedian: context.maeMedian ?? null,
    blackFallbackCount: audit.blackFallbackCount,
    horizontalOverflow: audit.horizontalOverflow,
    consoleErrors: evidence.consoleErrors.length,
    reactWarnings: evidence.reactWarnings.length,
    aiPostCount: evidence.aiPostCount,
  };
  evidence.acceptance.push(record);
  evidence.computedStyles.push({
    viewport, tab, instrument, horizon, ...audit,
  });
  return { record, audit };
}

async function drawingAudit(page) {
  await page.getByRole('button', { name: 'OVERVIEW', exact: true }).click();
  const chart = page.locator('.mr-chart');
  await chart.waitFor({ state: 'visible' });
  await page.getByRole('button', { name: '帯', exact: true }).click();
  const box = await chart.boundingBox();
  if (!box) throw new Error('drawing chart has no bounding box');
  await chart.click({ position: { x: box.width * .35, y: box.height * .45 } });
  await chart.click({ position: { x: box.width * .58, y: box.height * .62 } });
  await page.getByRole('button', { name: '選択', exact: true }).click();
  const drawing = page.locator('.mr-my-layer rect').last();
  await drawing.click();
  return page.evaluate(() => ({
    drawingCount: document.querySelectorAll('.mr-my-layer rect, .mr-my-layer line').length,
    handleCount: document.querySelectorAll('.mr-selection-handle').length,
    handles: [...document.querySelectorAll('.mr-selection-handle')].map((element) => ({
      fill: getComputedStyle(element).fill,
      stroke: getComputedStyle(element).stroke,
    })),
  }));
}

async function deployedAssets(page) {
  return page.evaluate(async (base) => {
    const html = await fetch(`${base}index.html?cb=${Date.now()}`, { cache: 'no-store' })
      .then((response) => response.text());
    const expected = [...html.matchAll(/assets\/[^"'<>]+\.(?:js|css)/g)]
      .map((match) => match[0].split('/').pop());
    const active = [...document.querySelectorAll('script[src],link[rel="stylesheet"][href]')]
      .map((element) => (element.src || element.href || '').split('/').pop()?.split('?')[0])
      .filter(Boolean);
    return {
      expected: [...new Set(expected)].sort(),
      active: [...new Set(active)].sort(),
      mixed: active.some((asset) => /^index-.*\.(?:js|css)$/.test(asset)
        && !expected.includes(asset)),
    };
  }, new URL(PUBLIC_URL).pathname);
}

async function firstUseLoaderAudit(browser, evidence) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    serviceWorkers: 'block',
  });
  await context.addInitScript(() => {
    globalThis.__ARGUS_LOADER_FIRST_AT__ = null;
    const observe = () => {
      const root = document.documentElement;
      if (!root) return;
      const record = () => {
        if (globalThis.__ARGUS_LOADER_FIRST_AT__ == null
            && document.querySelector('.triangle-step-loader')) {
          globalThis.__ARGUS_LOADER_FIRST_AT__ = performance.now();
        }
      };
      new MutationObserver(record).observe(root, {
        childList: true, subtree: true,
      });
      record();
    };
    if (document.documentElement) observe();
    else document.addEventListener('DOMContentLoaded', observe, { once: true });
  });
  const page = await context.newPage();
  attachEvidence(page, evidence);
  let resolveRequestStart;
  const requestStart = new Promise((resolve) => {
    resolveRequestStart = resolve;
  });
  await page.route('**/api/argus/chart-intelligence?*', async (route) => {
    const parsed = new URL(route.request().url());
    if (parsed.searchParams.get('snapshot') === 'verified') {
      resolveRequestStart?.(Date.now());
      resolveRequestStart = null;
      await new Promise((resolve) => setTimeout(resolve, 6_200));
    }
    await route.continue();
  });
  await page.goto(NORMAL_URL, {
    waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
  });
  await waitForVersion(page, EXPECTED_VERSION);
  const startedAt = await Promise.race([
    requestStart,
    new Promise((_, reject) => setTimeout(
      () => reject(new Error('verified snapshot request did not start')),
      5_000)),
  ]);
  await page.waitForTimeout(Math.max(0, 200 - (Date.now() - startedAt)));
  const beforeThreshold = await page.locator(
    '.triangle-step-loader').count();
  await page.waitForTimeout(Math.max(0, 300 - (Date.now() - startedAt)));
  const afterThreshold = await page.locator(
    '.triangle-step-loader').count();
  const loaderTiming = await page.evaluate(() => {
    const entries = performance.getEntriesByName(
      'argus-snapshot:network-revalidation-start');
    const networkStart = entries.length
      ? entries[entries.length - 1].startTime : null;
    const firstLoaderAt = globalThis.__ARGUS_LOADER_FIRST_AT__;
    return {
      networkStart,
      firstLoaderAt,
      loaderDelayMs: networkStart != null && firstLoaderAt != null
        ? firstLoaderAt - networkStart : null,
    };
  });
  const skeletonCount = await page.locator(
    '.mr-snapshot-skeleton').count();
  await page.waitForTimeout(Math.max(0, 5_250 - (Date.now() - startedAt)));
  const slowLabel = await page.locator(
    '.mr-snapshot-skeleton').innerText().catch(() => '');
  const screenshot = await captureScreenshot(
    page, evidence, '1280x800-first-use-loader.png',
    'first-use-loader');
  await waitForData(page, 30_000);
  const chartCount = await page.locator(
    '.market-replay[data-snapshot-id]').count();
  const result = {
    beforeThreshold, afterThreshold, skeletonCount,
    beforeThresholdAtMs: 200, afterThresholdAtMs: 300,
    loaderTiming, slowLabel, chartCount,
  };
  if (loaderTiming.loaderDelayMs == null) {
    evidence.failures.push('loader-timing-missing');
  } else if (loaderTiming.loaderDelayMs < 225) {
    evidence.failures.push(
      `loader-flicker-before-225ms:${loaderTiming.loaderDelayMs}`);
  }
  if (!skeletonCount) evidence.failures.push('first-use-skeleton-missing');
  if (!slowLabel.includes('初回データを準備中')) {
    evidence.failures.push('first-use-five-second-label-missing');
  }
  if (!chartCount) evidence.failures.push('first-use-chart-missing');
  await context.close();
  return { result, screenshot };
}

async function mainAcceptance() {
  await fs.rm(OUT_DIR, { recursive: true, force: true });
  await fs.mkdir(path.join(OUT_DIR, 'screenshots'), { recursive: true });
  const evidence = {
    acceptance: [], consoleErrors: [], reactWarnings: [], network: [],
    marketData: {}, computedStyles: [], aiPostCount: 0, failures: [],
  };
  const browser = await chromium.launch({ headless: true });
  let screenshotCount = 0;
  const fresh = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    serviceWorkers: 'allow',
  });
  const page = await fresh.newPage();
  attachEvidence(page, evidence);
  const freshBefore = { serviceWorkerCount: 0, cacheNames: [] };
  const publicIdentity = await waitForBackendIdentity(page.request);
  console.log('public-market-acceptance: backend-ready');
  await waitForMarketCache(page.request);
  console.log('public-market-acceptance: market-cache-ready');
  const firstUse = await firstUseLoaderAudit(browser, evidence);
  if (firstUse.screenshot) screenshotCount += 1;
  await page.goto(NORMAL_URL, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS });
  await waitForVersion(page, EXPECTED_VERSION);
  await waitForMarket(page);
  const initialDataLoadMs = await waitForData(page);
  if (initialDataLoadMs > DATA_TIMEOUT_MS) evidence.failures.push(`initial-pending:${initialDataLoadMs}`);
  const backendBody = publicIdentity.body;
  const backend = backendBody.buildIdentity || {};
  const actualSha = await page.evaluate(() => globalThis.__ARGUS_BUILD_SHA__ || null);
  if (actualSha !== EXPECTED_SHA) evidence.failures.push(`frontend-sha:${actualSha}:${EXPECTED_SHA}`);
  if (await page.evaluate(() => location.hash) !== '#market') evidence.failures.push('normal-url-deeplink');

  for (const instrument of INSTRUMENTS) {
    await page.getByRole('button', { name: instrument, exact: true }).click();
    const instrumentLoadMs = await waitForData(page);
    for (const horizon of HORIZONS) {
      await page.getByRole('button', { name: horizon, exact: true }).click();
      const horizonLoadMs = await waitForData(page);
      for (const tab of TABS) {
        await page.getByRole('button', { name: tab, exact: true }).click();
        const { record, audit } = await recordCombination(
          page, evidence, backend, { width: 1280, height: 800 },
          tab, instrument, horizon, Math.max(instrumentLoadMs, horizonLoadMs));
        validateStyles(audit, evidence.failures, `${instrument}:${horizon}:${tab}`, tab);
        if (!record.datasetHash) evidence.failures.push(`${instrument}:${horizon}:no-dataset-hash`);
        if (!record.snapshotId
            || record.snapshotId !== record.responseSnapshotId) {
          evidence.failures.push(
            `${instrument}:${horizon}:snapshot-id-mismatch`);
        }
        if (!['hit', 'updated'].includes(record.cacheStatus)) {
          evidence.failures.push(
            `${instrument}:${horizon}:cache-${record.cacheStatus}`);
        }
        if (record.replayMethodVersion !== 'market-context-replay-v2-standard-excursion') {
          evidence.failures.push(`${instrument}:${horizon}:method-${record.replayMethodVersion}`);
        }
        if (record.maeQ90 != null && record.maeQ90 > 0) {
          evidence.failures.push(`${instrument}:${horizon}:mae-q90-positive`);
        }
      }
    }
  }
  console.log(`public-market-acceptance: combinations=${evidence.acceptance.length}`);

  await page.getByRole('button', { name: '1321', exact: true }).click();
  await page.getByRole('button', { name: '5D', exact: true }).click();
  for (const viewport of VIEWPORTS) {
    await page.setViewportSize(viewport);
    for (const tab of TABS) {
      await page.getByRole('button', { name: tab, exact: true }).click();
      const audit = await styleAudit(page);
      evidence.computedStyles.push({
        viewport, tab, instrument: '1321', horizon: '5D',
        screenshot: true, ...audit,
      });
      validateStyles(audit, evidence.failures,
        `${viewport.width}x${viewport.height}:${tab}`, tab);
      const representative = tab === 'OVERVIEW' || viewport.width === 1280;
      if (representative && await captureScreenshot(
        page,
        evidence,
        `${viewport.width}x${viewport.height}-${tab.toLowerCase()}.png`,
        `${viewport.width}x${viewport.height}:${tab}`,
      )) screenshotCount += 1;
    }
  }
  console.log(`public-market-acceptance: screenshots=${screenshotCount}`);
  await page.setViewportSize({ width: 1280, height: 800 });
  const drawing = await drawingAudit(page);
  if (drawing.handleCount < 2 || drawing.handles.some((row) => isBlack(row.fill))) {
    evidence.failures.push('drawing-handles-invisible');
  }
  if (await captureScreenshot(
    page, evidence, '1280x800-drawing-selected.png', '1280x800:drawing-selected',
  )) screenshotCount += 1;

  await page.goto(CACHE_BUSTED_URL, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS });
  await waitForVersion(page, EXPECTED_VERSION);
  await waitForMarket(page);
  await waitForData(page);
  const freshAfter = await page.evaluate(async () => ({
    frontendVersion: globalThis.__ARGUS_VERSION__ || null,
    frontendBuildSha: globalThis.__ARGUS_BUILD_SHA__ || null,
    serviceWorkerCount: (await navigator.serviceWorker.getRegistrations()).length,
    cacheNames: await caches.keys(),
  }));
  await fresh.close();
  await browser.close();

  // Upgrade the pre-deploy profile once, seed verified IndexedDB entries, and
  // persist a non-default UI state before a full browser close.
  const warmSeedContext = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: true,
    viewport: { width: 1280, height: 800 },
  });
  const warmSeedPage = warmSeedContext.pages()[0] || await warmSeedContext.newPage();
  attachEvidence(warmSeedPage, evidence);
  await warmSeedPage.goto(NORMAL_URL, {
    waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
  });
  await waitForVersion(warmSeedPage, EXPECTED_VERSION, PAGE_TIMEOUT_MS);
  await waitForMarket(warmSeedPage);
  await waitForData(warmSeedPage, 30_000);
  await warmSeedPage.getByRole('button', { name: 'SPY', exact: true }).click();
  await warmSeedPage.getByRole('button', { name: '5D', exact: true }).click();
  await waitForData(warmSeedPage, 30_000);
  await warmSeedPage.getByRole('button', { name: 'QQQ', exact: true }).click();
  await warmSeedPage.getByRole('button', { name: '20D', exact: true }).click();
  await warmSeedPage.getByRole('button', { name: 'OVERVIEW', exact: true }).click();
  await warmSeedPage.getByRole('button', { name: '3M', exact: true }).click();
  const overlays = warmSeedPage.locator('details.mr-overlays');
  if (!await overlays.evaluate((element) => element.open)) {
    await overlays.locator('summary').click();
  }
  await warmSeedPage.getByRole('button', { name: 'REPLAY', exact: true }).click();
  await waitForData(warmSeedPage, 30_000);
  const warmSeedSnapshotId = await warmSeedPage.locator(
    '.market-replay[data-snapshot-id]').getAttribute('data-snapshot-id');
  const assets = await deployedAssets(warmSeedPage);
  if (assets.mixed) evidence.failures.push('pwa-mixed-old-assets');
  const warmOnline = await warmSeedPage.evaluate(async () => ({
    frontendVersion: globalThis.__ARGUS_VERSION__ || null,
    frontendBuildSha: globalThis.__ARGUS_BUILD_SHA__ || null,
    serviceWorkerCount: (await navigator.serviceWorker.getRegistrations()).length,
    cacheNames: await caches.keys(),
  }));
  if (warmOnline.serviceWorkerCount !== 1) {
    evidence.failures.push(
      `warm-service-worker-count:${warmOnline.serviceWorkerCount}`);
  }
  await warmSeedContext.close();

  // Use an isolated copy for the controlled network-delay test. Unregister its
  // Service Worker so Chromium cannot satisfy the request from runtime Cache
  // Storage before Playwright applies the 12-second route. The original PWA
  // profile remains intact for the later real offline-restart proof.
  const slowProfileDir = `${PROFILE_DIR}-controlled-delay`;
  await fs.rm(slowProfileDir, { recursive: true, force: true });
  await fs.cp(PROFILE_DIR, slowProfileDir, { recursive: true });
  const slowPrepContext = await chromium.launchPersistentContext(slowProfileDir, {
    headless: true,
    viewport: { width: 1280, height: 800 },
    serviceWorkers: 'allow',
  });
  const slowPrepPage = slowPrepContext.pages()[0]
    || await slowPrepContext.newPage();
  await slowPrepPage.goto(NORMAL_URL, {
    waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
  });
  const slowProfilePreparation = await slowPrepPage.evaluate(async () => {
    const registrations = await navigator.serviceWorker.getRegistrations();
    const unregistered = (await Promise.all(
      registrations.map((registration) => registration.unregister()),
    )).filter(Boolean).length;
    const removedRuntimeApiCaches = (await caches.keys())
      .filter((name) => name === 'argus-api');
    await Promise.all(removedRuntimeApiCaches.map((name) => caches.delete(name)));
    return { unregistered, removedRuntimeApiCaches };
  });
  await slowPrepContext.close();

  // Reopen the exact profile with SW interception disabled only for this
  // controlled 12-second backend-delay test. IndexedDB remains the source of
  // the first chart; no production latency setting is changed.
  const slowContext = await chromium.launchPersistentContext(slowProfileDir, {
    headless: true,
    viewport: { width: 1280, height: 800 },
    serviceWorkers: 'block',
  });
  let resolveSlowRequest;
  const slowRequestStarted = new Promise((resolve) => {
    resolveSlowRequest = resolve;
  });
  let delayedReadCount = 0;
  await slowContext.route('**/api/argus/chart-intelligence?*', async (route) => {
    const parsed = new URL(route.request().url());
    if (parsed.searchParams.get('snapshot') === 'verified') {
      delayedReadCount += 1;
      resolveSlowRequest?.(Date.now());
      resolveSlowRequest = null;
      await new Promise((resolve) => setTimeout(resolve, 12_000));
    }
    await route.continue();
  });
  const slowPage = slowContext.pages()[0] || await slowContext.newPage();
  attachEvidence(slowPage, evidence);
  const warmStarted = Date.now();
  await slowPage.goto(NORMAL_URL, {
    waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
  });
  await waitForVersion(slowPage, EXPECTED_VERSION, PAGE_TIMEOUT_MS);
  await waitForMarket(slowPage);
  await slowPage.locator(
    '.market-replay[data-snapshot-id]').waitFor({ timeout: 500 });
  const controlledDelayStartedAt = await Promise.race([
    slowRequestStarted,
    new Promise((_, reject) => setTimeout(
      () => reject(new Error('controlled verified snapshot delay did not start')),
      5_000)),
  ]);
  const warmNavigationToChartMs = Date.now() - warmStarted;
  const warmTiming = await slowPage.evaluate(() => {
    const lastMark = (name) => {
      const entries = performance.getEntriesByName(`argus-snapshot:${name}`);
      return entries.length ? entries[entries.length - 1].startTime : null;
    };
    const navigationStart = lastMark('navigation-start');
    const cachedChart = lastMark('first-cached-chart-render');
    return {
      navigationStart,
      cachedChart,
      cacheRestoreMs: navigationStart != null && cachedChart != null
        ? Math.max(0, cachedChart - navigationStart) : null,
    };
  });
  const warmCachedRenderMs = warmTiming.cacheRestoreMs;
  await slowPage.waitForTimeout(350);
  const loaderDuringRevalidation = await slowPage.locator(
    '.mr-snapshot-status .triangle-step-loader').count();
  const restoredTab = await slowPage.getByRole(
    'button', { name: 'REPLAY', exact: true }).getAttribute('aria-selected');
  await slowPage.getByRole(
    'button', { name: 'OVERVIEW', exact: true }).click();
  const restoredState = {
    instrument: await slowPage.getByRole(
      'button', { name: 'QQQ', exact: true }).getAttribute('class'),
    horizon: await slowPage.getByRole(
      'button', { name: '20D', exact: true }).getAttribute('class'),
    tab: restoredTab,
    range: await slowPage.getByRole(
      'button', { name: '3M', exact: true }).getAttribute('class'),
    overlaysOpen: await slowPage.locator(
      'details.mr-overlays').evaluate((element) => element.open),
  };
  await slowPage.getByRole(
    'button', { name: 'REPLAY', exact: true }).click();
  const slowSnapshotBefore = await slowPage.locator(
    '.market-replay[data-snapshot-id]').getAttribute('data-snapshot-id');
  if (await captureScreenshot(
    slowPage, evidence, '1280x800-warm-slow-revalidation.png',
    'warm-slow-revalidation',
  )) screenshotCount += 1;
  await slowPage.waitForTimeout(12_200);
  await waitForData(slowPage, 30_000);
  const slowSnapshotAfter = await slowPage.locator(
    '.market-replay[data-snapshot-id]').getAttribute('data-snapshot-id');
  const networkResponseAt = await slowPage.evaluate(() => {
    const entries = performance.getEntriesByName('argus-snapshot:network-response');
    return entries.length ? entries[entries.length - 1].startTime : null;
  });
  if (warmCachedRenderMs == null) {
    evidence.failures.push('warm-cache-timing-missing');
  } else if (warmCachedRenderMs > 500) {
    evidence.failures.push(`warm-cache-over-500ms:${warmCachedRenderMs}`);
  }
  if (warmTiming.cachedChart == null || networkResponseAt == null
      || warmTiming.cachedChart >= networkResponseAt) {
    evidence.failures.push('warm-cache-not-before-network');
  }
  if (!loaderDuringRevalidation) {
    evidence.failures.push('warm-revalidation-loader-missing');
  }
  if (slowSnapshotBefore !== warmSeedSnapshotId
      || slowSnapshotAfter !== warmSeedSnapshotId) {
    evidence.failures.push('warm-snapshot-continuity');
  }
  if (!String(restoredState.instrument).includes('active')
      || !String(restoredState.horizon).includes('active')
      || restoredState.tab !== 'true'
      || !String(restoredState.range).includes('active')
      || !restoredState.overlaysOpen) {
    evidence.failures.push('warm-ui-state-not-restored');
  }

  // Stale-response race: SPY is delayed longer than QQQ. The final identity
  // must remain QQQ after both requests settle.
  await slowContext.unroute('**/api/argus/chart-intelligence?*');
  await slowContext.route('**/api/argus/chart-intelligence?*', async (route) => {
    const parsed = new URL(route.request().url());
    const symbol = parsed.searchParams.get('symbol');
    await new Promise((resolve) => setTimeout(
      resolve, symbol === 'SPY' ? 1_200 : 100));
    await route.continue();
  });
  await slowPage.getByRole('button', { name: 'SPY', exact: true }).click();
  await slowPage.getByRole('button', { name: 'QQQ', exact: true }).click();
  await slowPage.waitForTimeout(1_500);
  const race = {
    heading: await slowPage.locator('.mr-header h2').innerText(),
    snapshotId: await slowPage.locator(
      '.market-replay[data-snapshot-id]').getAttribute('data-snapshot-id'),
    expectedSnapshotId: evidence.marketData.QQQ?.snapshotIds?.['20'] || null,
  };
  if (!race.heading.includes('QQQ') || !race.snapshotId
      || race.snapshotId !== race.expectedSnapshotId) {
    evidence.failures.push('asset-switching-race');
  }
  await slowContext.close();
  await fs.rm(slowProfileDir, { recursive: true, force: true });

  // Re-enable the installed Service Worker and prove the same verified
  // IndexedDB snapshot survives a fully offline restart.
  const offlineContext = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: true,
    viewport: { width: 1280, height: 800 },
  });
  const offlinePage = offlineContext.pages()[0] || await offlineContext.newPage();
  attachEvidence(offlinePage, evidence);
  await offlinePage.goto(NORMAL_URL, {
    waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
  });
  await waitForVersion(offlinePage, EXPECTED_VERSION);
  await waitForMarket(offlinePage);
  await waitForData(offlinePage, 30_000);
  await offlineContext.setOffline(true);
  await offlinePage.reload({
    waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
  });
  await waitForVersion(offlinePage, EXPECTED_VERSION);
  await waitForMarket(offlinePage);
  await offlinePage.locator(
    '.market-replay[data-snapshot-id]').waitFor({ timeout: 500 });
  const warmOffline = await offlinePage.evaluate(() => ({
    frontendVersion: globalThis.__ARGUS_VERSION__ || null,
    frontendBuildSha: globalThis.__ARGUS_BUILD_SHA__ || null,
    online: navigator.onLine,
    snapshotId: document.querySelector(
      '.market-replay[data-snapshot-id]')?.getAttribute('data-snapshot-id') || null,
    snapshotStatus: document.querySelector(
      '.mr-snapshot-status')?.textContent?.trim() || null,
  }));
  if (!warmOffline.snapshotId
      || warmOffline.snapshotId !== warmSeedSnapshotId
      || warmOffline.online !== false) {
    evidence.failures.push('offline-verified-snapshot-fallback');
  }
  await offlineContext.setOffline(false);
  await offlineContext.close();

  const warmPerformance = {
    warmCachedRenderMs,
    warmNavigationToChartMs,
    warmTiming,
    networkResponseAt,
    controlledDelayStartedAt,
    delayedReadCount,
    slowProfilePreparation,
    loaderDuringRevalidation,
    snapshotBefore: slowSnapshotBefore,
    snapshotAfter: slowSnapshotAfter,
    restoredState,
    race,
    controlledBackendDelayMs: 12_000,
  };

  if (evidence.consoleErrors.length) evidence.failures.push('console-errors');
  if (evidence.reactWarnings.length) evidence.failures.push('react-warnings');
  if (evidence.aiPostCount) evidence.failures.push(`automatic-posts:${evidence.aiPostCount}`);

  const testedAt = new Date().toISOString();
  const version = {
    testedAt,
    publicUrl: NORMAL_URL,
    cacheBustedUrl: CACHE_BUSTED_URL,
    frontendVersion: EXPECTED_VERSION,
    frontendBuildSha: EXPECTED_SHA,
    backendVersion: backend.backendVersion || backend.appVersion || null,
    backendBuildSha: backend.backendBuildSha || null,
  };
  const pwa = {
    freshBefore, freshAfter, warmOnline, warmOffline, assets,
    firstUse: firstUse.result, warmPerformance,
  };
  const acceptance = {
    marketProductStatus: evidence.failures.length ? 'NOT_FROZEN' : 'FROZEN',
    testedAt,
    publicUrl: NORMAL_URL,
    cacheBustedUrl: CACHE_BUSTED_URL,
    combinationCount: evidence.acceptance.length,
    screenshotCount,
    initialDataLoadMs,
    drawing,
    pwa,
    failures: [...new Set(evidence.failures)].sort(),
    records: evidence.acceptance,
  };
  await writeJson('acceptance.json', acceptance);
  await writeJson('console.json', {
    errors: evidence.consoleErrors, reactWarnings: evidence.reactWarnings,
  });
  await writeJson('network.json', {
    aiPostCount: evidence.aiPostCount,
    requests: evidence.network,
  });
  await writeJson('computed-styles.json', evidence.computedStyles);
  await writeJson('version.json', version);
  if (evidence.failures.length) {
    throw new Error(`public acceptance failed: ${[...new Set(evidence.failures)].join(', ')}`);
  }
  console.log(`public-market-acceptance: PASS (${evidence.acceptance.length} combinations)`);
}

if (MODE === 'seed') {
  seedWarmProfile()
    .then((result) => console.log(`public-market-acceptance seed: ${JSON.stringify(result)}`))
    .catch((error) => {
      console.error(sanitize(error.stack || error.message));
      process.exit(1);
    });
} else {
  mainAcceptance().catch(async (error) => {
    const testedAt = new Date().toISOString();
    const failure = sanitize(error.stack || error.message);
    await fs.mkdir(path.join(OUT_DIR, 'screenshots'), { recursive: true });
    try {
      await fs.access(path.join(OUT_DIR, 'acceptance.json'));
    } catch {
      await Promise.all([
        writeJson('acceptance.json', {
          marketProductStatus: 'NOT_FROZEN',
          testedAt,
          publicUrl: NORMAL_URL,
          cacheBustedUrl: CACHE_BUSTED_URL,
          failures: [failure],
        }),
        writeJson('console.json', { errors: [{ type: 'acceptance', message: failure }], reactWarnings: [] }),
        writeJson('network.json', { aiPostCount: null, requests: [] }),
        writeJson('computed-styles.json', []),
        writeJson('version.json', {
          testedAt,
          frontendVersion: EXPECTED_VERSION,
          frontendBuildSha: EXPECTED_SHA,
          backendVersion: EXPECTED_BACKEND_VERSION,
          backendBuildSha: null,
        }),
      ]);
    }
    console.error(failure);
    process.exit(1);
  });
}
