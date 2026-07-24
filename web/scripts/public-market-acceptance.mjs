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
      const symbol = String(body.symbol || parsed.searchParams.get('symbol') || '');
      const contexts = body.marketReplay?.contexts || {};
      evidence.marketData[symbol] = {
        cacheStatus: body.marketReplay?.cacheStatus || null,
        methodVersion: body.marketReplay?.methodVersion || null,
        stateHash: body.marketReplay?.stateHash || null,
        automaticAiCalls: body.marketReplay?.automaticAiCalls ?? null,
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
    } catch {
      evidence.consoleErrors.push({
        type: 'acceptance-parser',
        message: 'chart-intelligence response was not valid JSON',
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

async function mainAcceptance() {
  await fs.rm(OUT_DIR, { recursive: true, force: true });
  await fs.mkdir(path.join(OUT_DIR, 'screenshots'), { recursive: true });
  const evidence = {
    acceptance: [], consoleErrors: [], reactWarnings: [], network: [],
    marketData: {}, computedStyles: [], aiPostCount: 0, failures: [],
  };
  const browser = await chromium.launch({ headless: true });
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
        if (record.cacheStatus !== 'hit') evidence.failures.push(`${instrument}:${horizon}:cache-${record.cacheStatus}`);
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
  let screenshotCount = 0;
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

  const warmContext = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: true,
    viewport: { width: 1280, height: 800 },
  });
  const warmPage = warmContext.pages()[0] || await warmContext.newPage();
  attachEvidence(warmPage, evidence);
  await warmPage.goto(NORMAL_URL, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS });
  await waitForVersion(warmPage, EXPECTED_VERSION, PAGE_TIMEOUT_MS);
  await waitForMarket(warmPage);
  await waitForData(warmPage);
  const assets = await deployedAssets(warmPage);
  if (assets.mixed) evidence.failures.push('pwa-mixed-old-assets');
  const warmOnline = await warmPage.evaluate(async () => ({
    frontendVersion: globalThis.__ARGUS_VERSION__ || null,
    frontendBuildSha: globalThis.__ARGUS_BUILD_SHA__ || null,
    serviceWorkerCount: (await navigator.serviceWorker.getRegistrations()).length,
    cacheNames: await caches.keys(),
  }));
  await warmContext.setOffline(true);
  await warmPage.reload({ waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS });
  await waitForVersion(warmPage, EXPECTED_VERSION);
  const warmOffline = await warmPage.evaluate(() => ({
    frontendVersion: globalThis.__ARGUS_VERSION__ || null,
    frontendBuildSha: globalThis.__ARGUS_BUILD_SHA__ || null,
  }));
  await warmContext.setOffline(false);
  await warmContext.close();

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
  const pwa = { freshBefore, freshAfter, warmOnline, warmOffline, assets };
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
    console.error(failure);
    process.exit(1);
  });
}
