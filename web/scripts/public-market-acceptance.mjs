import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {
  validateWarmProfile,
  writeWarmProfileManifest,
} from './warm-profile-contract.mjs';

const PUBLIC_URL = process.env.ARGUS_PUBLIC_URL || 'https://mitsugue.github.io/argus/';
const EXPECTED_VERSION = process.env.ARGUS_EXPECTED_VERSION || '';
const EXPECTED_SHA = process.env.ARGUS_EXPECTED_SHA || '';
const EXPECTED_BACKEND_VERSION = process.env.ARGUS_EXPECTED_BACKEND_VERSION || '';
const EXPECTED_BACKEND_SHA = process.env.ARGUS_EXPECTED_BACKEND_SHA || '';
const MODE = process.env.ARGUS_ACCEPTANCE_MODE || 'accept';
const OUT_DIR = path.resolve(process.env.ARGUS_ACCEPTANCE_OUT
  || '../artifacts/market-public-acceptance');
const PROFILE_DIR = path.resolve(process.env.ARGUS_WARM_PROFILE_DIR
  || '../artifacts/market-warm-profile');
const BACKEND_ORIGIN = (process.env.ARGUS_BACKEND_URL
  || 'https://argus-backend-3j2m.onrender.com').replace(/\/$/, '');
const TODAY_URL = `${PUBLIC_URL.replace(/\/?$/, '/')}#today`;
const DATA_TIMEOUT_MS = 5_000;
const PAGE_TIMEOUT_MS = 25_000;
const BACKEND_READY_TIMEOUT_MS = 8 * 60_000;
const MARKET_CACHE_READY_TIMEOUT_MS = 30 * 60_000;
const COMBINATION_PACE_MS = 1_000;
const SYMBOLS = ['1321', '1306', 'SPY', 'QQQ'];
const HORIZONS = ['1D', '5D', '20D'];
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 430, height: 932 },
  { width: 390, height: 844 },
];

const sanitize = (value) => String(value ?? '')
  .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
  .replace(/([?&](?:token|key|authorization|auth)=[^&\s]+)/gi, '?redacted')
  .slice(0, 800);

async function writeJson(name, value) {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(path.join(OUT_DIR, name),
    `${JSON.stringify(value, null, 2)}\n`);
}

async function screenshot(page, name) {
  await fs.mkdir(path.join(OUT_DIR, 'screenshots'), { recursive: true });
  await page.screenshot({
    path: path.join(OUT_DIR, 'screenshots', name),
    fullPage: false,
    animations: 'disabled',
    timeout: 10_000,
  });
}

async function retryUntil(request, url, timeoutMs, validate, label) {
  const deadline = Date.now() + timeoutMs;
  let last = 'unavailable';
  while (Date.now() < deadline) {
    try {
      const response = await request.get(url, { timeout: 30_000 });
      const body = await response.json().catch(() => null);
      if (response.ok() && validate(body, response.status())) return body;
      last = `${response.status()}:${JSON.stringify(body)?.slice(0, 200)}`;
    } catch (error) {
      last = sanitize(error?.message);
    }
    await new Promise((resolve) => setTimeout(resolve, 5_000));
  }
  throw new Error(`${label}: ${last}`);
}

async function waitForBackendIdentity(request) {
  const health = await retryUntil(request, `${BACKEND_ORIGIN}/healthz`,
    BACKEND_READY_TIMEOUT_MS,
    (body, status) => status === 200
      && body?.status === 'ok'
      && typeof body?.backendVersion === 'string'
      && /^[0-9a-f]{40}$/.test(body?.buildSha || ''),
    'backend identity did not become ready');
  return { service: {
    backendVersion: health.backendVersion,
    buildSha: health.buildSha,
    liveness: health.status,
  } };
}

async function waitForMarketCache(request) {
  const query = new URLSearchParams({
    scope: 'market', symbol: '1321', market: 'JP', timeframe: 'daily',
    horizon: HORIZONS[1], snapshot: 'verified',
  });
  return retryUntil(request,
    `${BACKEND_ORIGIN}/api/argus/chart-intelligence?${query}`,
    MARKET_CACHE_READY_TIMEOUT_MS,
    (body, status) => {
      const view = body?.payload || body;
      return status === 200 && body?.verificationStatus === 'verified'
        && (view?.automaticAiCalls ?? 0) === 0
        && Array.isArray(view?.indicators?.bars)
        && view.indicators.bars.length > 1;
    },
    'market cache did not become ready');
}

function observe(page, evidence) {
  page.on('console', (message) => {
    if (message.type() === 'error') evidence.console.push({
      type: 'console.error', message: sanitize(message.text()),
      location: sanitize(message.location().url),
    });
  });
  page.on('pageerror', (error) => evidence.console.push({
    type: 'pageerror', message: sanitize(error.message), location: '',
  }));
  page.on('request', (request) => {
    const url = new URL(request.url());
    evidence.network.push({
      method: request.method(), origin: url.origin, pathname: url.pathname,
      symbol: url.searchParams.get('symbol'),
      horizon: url.searchParams.get('horizon'),
      scope: url.searchParams.get('scope'),
      snapshot: url.searchParams.get('snapshot'),
    });
    if (request.method() === 'POST'
      && /argus-backend-.*\.onrender\.com$/.test(url.hostname)) {
      evidence.aiPostCount += 1;
    }
  });
  page.on('response', (response) => {
    const task = (async () => {
      const url = new URL(response.url());
      if (url.pathname !== '/api/argus/chart-intelligence'
        || response.status() !== 200) return;
      const body = await response.json().catch(() => null);
      if (!body) return;
      const view = body.payload || body;
      if ((view.automaticAiCalls ?? 0) !== 0) {
        evidence.failures.push(`automatic-ai:${url.searchParams.get('symbol')}`);
      }
      const horizon = url.searchParams.get('horizon');
      const context = view.marketReplay?.contexts?.[horizon];
      if (context?.datasetHash) evidence.datasetHashes.add(context.datasetHash);
      if (body.snapshotId) evidence.responseSnapshotIds.add(body.snapshotId);
    })();
    evidence.responseTasks.add(task);
    void task.finally(() => evidence.responseTasks.delete(task));
  });
}

async function drainResponses(evidence) {
  while (evidence.responseTasks.size) {
    await Promise.allSettled([...evidence.responseTasks]);
  }
}

async function waitForToday(page, timeout = 30_000) {
  await page.locator('.at-chart-status[data-snapshot-id]')
    .waitFor({ state: 'visible', timeout });
  await page.locator('.at-projection').waitFor({ state: 'visible', timeout });
}

async function selectCombination(page, symbol, horizon) {
  const label = symbol === '1321' ? '日経'
    : symbol === '1306' ? 'TOPIX' : symbol === 'SPY' ? 'S&P' : 'NASDAQ';
  await page.locator('.at-index-strip button').filter({ hasText: label }).click();
  await page.getByRole('group', { name: '予測期間' })
    .getByRole('button', { name: horizon, exact: true }).click();
  await waitForToday(page);
  await page.waitForFunction(({ expectedSymbol, expectedHorizon }) => {
    const heading = document.querySelector('.at-proj-heading b')?.textContent || '';
    const active = document.querySelector('.at-horizon button[aria-pressed="true"]')
      ?.textContent || '';
    return heading.includes(expectedSymbol) && active === expectedHorizon;
  }, { expectedSymbol: symbol, expectedHorizon: horizon },
  { timeout: DATA_TIMEOUT_MS });
  return page.evaluate(() => ({
    heading: document.querySelector('.at-proj-heading b')?.textContent || '',
    horizon: document.querySelector('.at-horizon button[aria-pressed="true"]')
      ?.textContent || '',
    snapshotId: document.querySelector('.at-chart-status')
      ?.getAttribute('data-snapshot-id') || null,
    snapshotState: document.querySelector('.at-chart-status')
      ?.getAttribute('data-snapshot-state') || null,
  }));
}

async function visualAudit(page, viewport) {
  await page.setViewportSize(viewport);
  return page.evaluate((size) => {
    const chart = document.querySelector('.at-projection');
    const background = chart ? getComputedStyle(chart).backgroundColor : null;
    const blackFallbackCount = [...document.querySelectorAll('.at-projection svg *')]
      .filter((element) => {
        const style = getComputedStyle(element);
        return style.fill === 'rgb(0, 0, 0)' || style.stroke === 'rgb(0, 0, 0)';
      }).length;
    return {
      viewport: size,
      background,
      blackFallbackCount,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
    };
  }, viewport);
}

async function profileRuntimeProof(page) {
  return page.evaluate(async () => {
    const registration = await Promise.race([
      navigator.serviceWorker.ready,
      new Promise((_, reject) => setTimeout(
        () => reject(new Error('service_worker_ready_timeout')), 30_000)),
    ]);
    const databaseNames = (await indexedDB.databases())
      .map((row) => row.name).filter(Boolean).sort();
    const verifiedSnapshotRecordCount = await new Promise((resolve, reject) => {
      const request = indexedDB.open('argus-verified-snapshots');
      request.onerror = () => reject(request.error || new Error('indexeddb_open_failed'));
      request.onsuccess = () => {
        const database = request.result;
        if (!database.objectStoreNames.contains('snapshots')) {
          database.close();
          resolve(0);
          return;
        }
        const count = database.transaction('snapshots', 'readonly')
          .objectStore('snapshots').count();
        count.onerror = () => reject(count.error || new Error('indexeddb_count_failed'));
        count.onsuccess = () => {
          database.close();
          resolve(count.result);
        };
      };
    });
    return {
      databaseNames,
      serviceWorkerReady: Boolean(registration?.active),
      verifiedSnapshotRecordCount,
    };
  });
}

async function run() {
  if (!['accept', 'profile', 'seed'].includes(MODE)) {
    throw new Error(`invalid acceptance mode: ${MODE}`);
  }
  await fs.rm(OUT_DIR, { recursive: true, force: true });
  let warmProfile = null;
  if (MODE === 'seed') {
    await fs.rm(PROFILE_DIR, { recursive: true, force: true });
  } else {
    warmProfile = await validateWarmProfile({
      profileDir: PROFILE_DIR, expectedCandidateSha: EXPECTED_SHA,
    });
  }
  const evidence = {
    failures: [], console: [], network: [], combinations: [], computedStyles: [],
    aiPostCount: 0, datasetHashes: new Set(), responseSnapshotIds: new Set(),
    responseTasks: new Set(),
  };
  const context = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: true,
    viewport: { width: 1280, height: 800 }, serviceWorkers: 'allow',
  });
  let contextClosed = false;
  const page = context.pages()[0] || await context.newPage();
  observe(page, evidence);
  try {
    const identity = await waitForBackendIdentity(page.request);
    const seeded = await waitForMarketCache(page.request);
    if (MODE === 'seed') {
      if (!EXPECTED_SHA) throw new Error('seed candidate SHA is required');
      await page.goto(TODAY_URL, {
        waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
      });
      await waitForToday(page);
      const record = await selectCombination(page, '1321', HORIZONS[1]);
      if (!record.snapshotId || record.horizon !== HORIZONS[1]) {
        throw new Error('seeded canonical 5D snapshot unavailable');
      }
      const runtimeProof = await profileRuntimeProof(page);
      const frontendVersion = await page.evaluate(() =>
        globalThis.__ARGUS_VERSION__ ?? null);
      const frontendSha = await page.evaluate(() =>
        globalThis.__ARGUS_BUILD_SHA__ ?? null);
      await drainResponses(evidence);
      await context.close();
      contextClosed = true;
      const manifest = await writeWarmProfileManifest({
        profileDir: PROFILE_DIR,
        candidateSha: EXPECTED_SHA,
        runtimeProof,
        source: {
          backendVersion: identity.service.backendVersion,
          backendSha: identity.service.buildSha,
          frontendVersion,
          frontendSha,
          publicUrl: TODAY_URL,
          seededSnapshotId: seeded.snapshotId,
        },
      });
      await writeJson('version.json', {
        backendVersion: identity.service.backendVersion,
        backendSha: identity.service.buildSha,
        frontendVersion,
        frontendSha,
        seededSnapshotId: seeded.snapshotId,
        warmProfileArtifactId: manifest.artifactId,
      });
      return;
    }

    await page.goto(TODAY_URL, {
      waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
    });
    if (MODE === 'accept' && EXPECTED_VERSION) {
      await page.waitForFunction((expected) =>
        globalThis.__ARGUS_VERSION__ === expected, EXPECTED_VERSION,
      { timeout: PAGE_TIMEOUT_MS });
    }
    if (MODE === 'accept' && EXPECTED_SHA) {
      await page.waitForFunction((expected) =>
        globalThis.__ARGUS_BUILD_SHA__ === expected, EXPECTED_SHA,
      { timeout: PAGE_TIMEOUT_MS });
    }
    await waitForToday(page);
    if (MODE === 'profile') {
      const record = await selectCombination(page, '1321', HORIZONS[1]);
      const result = {
        verdict: record.snapshotId && record.horizon === HORIZONS[1] ? 'PASS' : 'FAIL',
        candidateSha: EXPECTED_SHA,
        canonicalHorizon: record.horizon,
        seededSnapshotId: record.snapshotId,
        verifiedSnapshotHttpStatus: 200,
        warmProfileArtifactId: warmProfile.artifactId,
      };
      await writeJson('acceptance.json', result);
      if (result.verdict !== 'PASS') process.exitCode = 1;
      return;
    }
    if (await page.evaluate(() => location.hash) !== '#today') {
      evidence.failures.push('canonical-today-deeplink');
    }
    if (await page.locator('.at-index-strip button').count() !== 4) {
      evidence.failures.push('market-instrument-count');
    }

    for (const symbol of SYMBOLS) {
      for (const horizon of HORIZONS) {
        const record = await selectCombination(page, symbol, horizon);
        evidence.combinations.push({ symbol, horizon, ...record });
        if (!record.snapshotId) {
          evidence.failures.push(`missing-snapshot:${symbol}:${horizon}`);
        }
        await page.waitForTimeout(COMBINATION_PACE_MS);
      }
    }

    for (const viewport of VIEWPORTS) {
      const audit = await visualAudit(page, viewport);
      evidence.computedStyles.push(audit);
      if (audit.horizontalOverflow) {
        evidence.failures.push(`horizontal-overflow:${viewport.width}`);
      }
      if (audit.blackFallbackCount) {
        evidence.failures.push(`black-fallback:${viewport.width}`);
      }
      await screenshot(page, `today-${viewport.width}x${viewport.height}.png`);
    }
    await drainResponses(evidence);

    const frontendVersion = await page.evaluate(() =>
      globalThis.__ARGUS_VERSION__ ?? null);
    const frontendSha = await page.evaluate(() =>
      globalThis.__ARGUS_BUILD_SHA__ ?? null);
    const backendVersion = identity.service.backendVersion;
    const backendSha = identity.service.buildSha;
    if (EXPECTED_BACKEND_VERSION && backendVersion !== EXPECTED_BACKEND_VERSION) {
      evidence.failures.push(`backend-version:${backendVersion}`);
    }
    if (EXPECTED_BACKEND_SHA && backendSha !== EXPECTED_BACKEND_SHA) {
      evidence.failures.push(`backend-sha:${backendSha}`);
    }
    if (evidence.aiPostCount) evidence.failures.push(`ai-post:${evidence.aiPostCount}`);
    if (evidence.console.length) evidence.failures.push('console-errors');

    const result = {
      verdict: evidence.failures.length ? 'FAIL' : 'PASS',
      todayProductStatus: evidence.failures.length ? 'NOT_FROZEN' : 'FROZEN',
      testedAt: new Date().toISOString(),
      publicUrl: TODAY_URL,
      frontendVersion, frontendSha, backendVersion, backendSha,
      datasetHash: [...evidence.datasetHashes].sort(),
      responseSnapshotId: [...evidence.responseSnapshotIds].sort(),
      blackFallbackCount: evidence.computedStyles.reduce(
        (total, row) => total + row.blackFallbackCount, 0),
      horizontalOverflow: evidence.computedStyles.some(
        (row) => row.horizontalOverflow),
      aiPostCount: evidence.aiPostCount,
      combinations: evidence.combinations,
      failures: evidence.failures,
    };
    await writeJson('acceptance.json', result);
    await writeJson('console.json', evidence.console);
    await writeJson('network.json', evidence.network);
    await writeJson('computed-styles.json', evidence.computedStyles);
    await writeJson('version.json', {
      frontendVersion, frontendSha, backendVersion, backendSha,
    });
    if (evidence.failures.length) process.exitCode = 1;
  } catch (error) {
    const failure = {
      verdict: 'FAIL', todayProductStatus: 'NOT_FROZEN',
      testedAt: new Date().toISOString(), publicUrl: TODAY_URL,
      failures: [sanitize(error?.stack || error?.message || error)],
    };
    await writeJson('acceptance.json', failure);
    await writeJson('console.json', evidence.console);
    await writeJson('network.json', evidence.network);
    process.exitCode = 1;
  } finally {
    await drainResponses(evidence);
    if (!contextClosed) await context.close().catch(() => {});
  }
}

await run();
