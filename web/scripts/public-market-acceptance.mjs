import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {
  validateWarmProfile,
  writeWarmProfileManifest,
} from './warm-profile-contract.mjs';
import { stabilizeWarmProfileRuntime } from './warm-profile-runtime.mjs';
import {
  CANONICAL_SNAPSHOT_SELECTOR,
  openCanonicalEvidence,
  selectCanonical1321FiveDay,
} from './canonical-snapshot-selection.mjs';

const PUBLIC_URL = process.env.ARGUS_PUBLIC_URL || 'https://mitsugue.github.io/argus/';
const EXPECTED_VERSION = process.env.ARGUS_EXPECTED_VERSION || '';
const EXPECTED_SHA = process.env.ARGUS_EXPECTED_SHA || '';
const EXPECTED_BACKEND_VERSION = process.env.ARGUS_EXPECTED_BACKEND_VERSION || '';
const EXPECTED_BACKEND_SHA = process.env.ARGUS_EXPECTED_BACKEND_SHA || '';
const EXPECTED_PRODUCT_VERSION = process.env.ARGUS_EXPECTED_PRODUCT_VERSION || '';
const REQUIRE_LIVE_CANDIDATE =
  process.env.ARGUS_REQUIRE_LIVE_CANDIDATE === 'true';
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
const RUNTIME_PROBE_TIMEOUT_MS = 10_000;
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

async function profileInventory(profileDir) {
  const root = await fs.stat(profileDir).catch(() => null);
  if (!root?.isDirectory()) return { exists: false, fileCount: 0, totalBytes: 0 };
  const pending = [profileDir];
  let fileCount = 0;
  let totalBytes = 0;
  while (pending.length) {
    const current = pending.pop();
    for (const entry of await fs.readdir(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name);
      if (entry.isDirectory()) pending.push(target);
      if (entry.isFile()) {
        const stat = await fs.stat(target);
        fileCount += 1;
        totalBytes += stat.size;
      }
    }
  }
  return { exists: true, fileCount, totalBytes };
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
      if (url.origin === new URL(PUBLIC_URL).origin || url.origin === BACKEND_ORIGIN) {
        evidence.responses.push({
          origin: url.origin,
          pathname: url.pathname,
          status: response.status(),
        });
      }
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
  await page.locator(CANONICAL_SNAPSHOT_SELECTOR)
    .waitFor({ state: 'visible', timeout });
  await openCanonicalEvidence(page, timeout);
}

async function selectCombination(page, symbol, horizon) {
  await openCanonicalEvidence(page);
  await page.locator(`[data-argus-control="market-instrument"][data-instrument="${symbol}"]`)
    .click();
  await page.locator(`[data-argus-control="canonical-horizon"][data-horizon="${horizon}"]`)
    .click();
  await waitForToday(page);
  await page.waitForFunction(({ expectedSymbol, expectedHorizon }) => {
    const heading = document.querySelector('.at-proj-heading b')?.textContent || '';
    const active = document.querySelector('.at-horizon button[aria-pressed="true"]')
      ?.textContent || '';
    const contract = document.querySelector(
      '[data-argus-contract="canonical-market-snapshot-v1"]');
    return heading.includes(expectedSymbol) && active === expectedHorizon
      && contract?.getAttribute('data-canonical-verification') === 'verified'
      && contract?.getAttribute('data-canonical-instrument') === expectedSymbol
      && contract?.getAttribute('data-canonical-horizon') === expectedHorizon
      && Boolean(contract?.getAttribute('data-canonical-snapshot-id'));
  }, { expectedSymbol: symbol, expectedHorizon: horizon },
  { timeout: DATA_TIMEOUT_MS });
  return page.evaluate(() => ({
    heading: document.querySelector('.at-proj-heading b')?.textContent || '',
    horizon: document.querySelector('.at-horizon button[aria-pressed="true"]')
      ?.textContent || '',
    snapshotId: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
      ?.getAttribute('data-canonical-snapshot-id') || null,
    snapshotState: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
      ?.getAttribute('data-canonical-snapshot-state') || null,
    verification: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
      ?.getAttribute('data-canonical-verification') || null,
    instrument: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
      ?.getAttribute('data-canonical-instrument') || null,
    canonicalHorizon: document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')
      ?.getAttribute('data-canonical-horizon') || null,
  }));
}

async function visualAudit(page, viewport) {
  await page.setViewportSize(viewport);
  return page.evaluate((size) => {
    const chart = document.querySelector('.at-projection');
    const background = chart ? getComputedStyle(chart).backgroundColor : null;
    const fillPaintTags = new Set([
      'circle', 'ellipse', 'path', 'polygon', 'polyline', 'rect', 'text', 'tspan', 'use',
    ]);
    const strokePaintTags = new Set([
      'circle', 'ellipse', 'line', 'path', 'polygon', 'polyline', 'rect', 'text', 'use',
    ]);
    const blackFallbackCount = [...document.querySelectorAll('.at-projection svg *')]
      .filter((element) => {
        const style = getComputedStyle(element);
        const tag = element.tagName.toLowerCase();
        const visible = style.display !== 'none' && style.visibility !== 'hidden'
          && Number.parseFloat(style.opacity || '1') > 0;
        return visible && (
          (fillPaintTags.has(tag) && style.fill === 'rgb(0, 0, 0)'
            && Number.parseFloat(style.fillOpacity || '1') > 0)
          || (strokePaintTags.has(tag) && style.stroke === 'rgb(0, 0, 0)'
            && Number.parseFloat(style.strokeOpacity || '1') > 0)
        );
      }).length;
    return {
      viewport: size,
      background,
      blackFallbackCount,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
    };
  }, viewport);
}

async function probeProfileRuntime(page) {
  return page.evaluate(async (timeoutMs) => {
    let registration = null;
    let readyError = null;
    try {
      registration = await Promise.race([
      navigator.serviceWorker.ready,
      new Promise((_, reject) => setTimeout(
          () => reject(new Error('service_worker_ready_timeout')), timeoutMs)),
      ]);
    } catch (error) {
      readyError = String(error?.message || error || 'unknown').slice(0, 200);
    }
    const registrations = await navigator.serviceWorker.getRegistrations();
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
      serviceWorker: {
        controller: Boolean(navigator.serviceWorker.controller),
        readyError,
        registrations: registrations.map((row) => ({
          scope: row.scope,
          scriptURL: row.active?.scriptURL || null,
          state: row.active?.state || null,
        })),
      },
    };
  }, RUNTIME_PROBE_TIMEOUT_MS);
}

async function run() {
  if (!['accept', 'profile', 'seed'].includes(MODE)) {
    throw new Error(`invalid acceptance mode: ${MODE}`);
  }
  await fs.rm(OUT_DIR, { recursive: true, force: true });
  const evidence = {
    failures: [], console: [], network: [], responses: [], phases: [],
    runtimeAttempts: [], combinations: [], computedStyles: [], releaseStateLog: [],
    aiPostCount: 0, datasetHashes: new Set(), responseSnapshotIds: new Set(),
    responseTasks: new Set(),
  };
  const environment = {
    acceptanceMode: MODE,
    backendOrigin: BACKEND_ORIGIN,
    expectedCandidateSha: EXPECTED_SHA || null,
    nodeVersion: process.version,
    publicOrigin: new URL(PUBLIC_URL).origin,
    todayUrl: TODAY_URL,
  };
  const markPhase = (phase, status = 'PASS', detail = null) => {
    evidence.phases.push({
      at: new Date().toISOString(), detail, phase, status,
    });
  };
  const diagnostics = async (verdict) => ({
    schemaVersion: 'argus-warm-profile-seed-diagnostics-v1',
    verdict,
    environment,
    phases: evidence.phases,
    runtimeAttempts: evidence.runtimeAttempts,
    releaseStateLog: evidence.releaseStateLog,
    console: evidence.console.slice(-64),
    network: evidence.network.slice(-256),
    responses: evidence.responses.slice(-256),
    profile: await profileInventory(PROFILE_DIR),
  });
  let warmProfile = null;
  let context = null;
  let page = null;
  let contextClosed = false;
  let finalReleaseMachine = null;
  try {
    markPhase('prepare-profile');
    if (MODE === 'seed') {
      await fs.rm(PROFILE_DIR, { recursive: true, force: true });
    } else {
      warmProfile = await validateWarmProfile({
        profileDir: PROFILE_DIR, expectedCandidateSha: EXPECTED_SHA,
      });
    }
    markPhase('launch-browser');
    context = await chromium.launchPersistentContext(PROFILE_DIR, {
      headless: true,
      viewport: { width: 1280, height: 800 }, serviceWorkers: 'allow',
    });
    environment.browserVersion = context.browser()?.version() || 'unknown';
    page = context.pages()[0] || await context.newPage();
    observe(page, evidence);
    markPhase('backend-identity');
    const identity = await waitForBackendIdentity(page.request);
    if (MODE === 'seed' && REQUIRE_LIVE_CANDIDATE) {
      if (identity.service.backendVersion !== EXPECTED_BACKEND_VERSION
          || identity.service.buildSha !== EXPECTED_BACKEND_SHA) {
        throw new Error(`candidate_backend_not_live:${JSON.stringify({
          expectedVersion: EXPECTED_BACKEND_VERSION,
          expectedSha: EXPECTED_BACKEND_SHA,
          observedVersion: identity.service.backendVersion,
          observedSha: identity.service.buildSha,
        })}`);
      }
    }
    markPhase('market-cache-5D');
    const seeded = await waitForMarketCache(page.request);
    if (MODE === 'seed') {
      if (!EXPECTED_SHA) throw new Error('seed candidate SHA is required');
      markPhase('navigate-today');
      await page.goto(TODAY_URL, {
        waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
      });
      if (REQUIRE_LIVE_CANDIDATE) {
        const observedFrontend = await page.evaluate(() => ({
          productVersion: globalThis.__ARGUS_PRODUCT_VERSION__ ?? null,
          frontendVersion: globalThis.__ARGUS_VERSION__ ?? null,
          frontendSha: globalThis.__ARGUS_BUILD_SHA__ ?? null,
        }));
        if (observedFrontend.productVersion !== EXPECTED_PRODUCT_VERSION
            || observedFrontend.frontendVersion !== EXPECTED_VERSION
            || observedFrontend.frontendSha !== EXPECTED_SHA) {
          throw new Error(`candidate_frontend_not_live:${JSON.stringify({
            expectedProductVersion: EXPECTED_PRODUCT_VERSION,
            expectedVersion: EXPECTED_VERSION,
            expectedSha: EXPECTED_SHA,
            observed: observedFrontend,
          })}`);
        }
        markPhase('candidate-release-identity-exact', 'PASS', {
          ...observedFrontend,
          backendVersion: identity.service.backendVersion,
          backendSha: identity.service.buildSha,
        });
      }
      markPhase('stabilize-today-1321-5D-service-worker-indexeddb');
      const stabilized = await stabilizeWarmProfileRuntime({
        probe: async (attempt) => {
          markPhase('runtime-probe', 'RUNNING', { attempt });
          const canonical = await selectCanonical1321FiveDay(page, {
            expectedSnapshotId: seeded.snapshotId,
            onTransition: (event) => {
              if (!event.detail?.assumed) {
                evidence.releaseStateLog.push({ ...event, attempt });
              }
            },
          });
          finalReleaseMachine = canonical.machine;
          if (!canonical.responseSnapshotId
              || canonical.responseSnapshotId !== canonical.uiSnapshotId) {
            throw new Error('seeded_canonical_5D_snapshot_unavailable');
          }
          const runtime = await probeProfileRuntime(page);
          return { ...runtime, canonical };
        },
        reload: async (attempt) => {
          markPhase('runtime-reload', 'RETRY', { attempt });
          await page.reload({
            waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT_MS,
          });
        },
      });
      evidence.runtimeAttempts = stabilized.diagnostics;
      const frontendVersion = await page.evaluate(() =>
        globalThis.__ARGUS_VERSION__ ?? null);
      const frontendSha = await page.evaluate(() =>
        globalThis.__ARGUS_BUILD_SHA__ ?? null);
      await drainResponses(evidence);
      markPhase('close-browser');
      await context.close();
      contextClosed = true;
      markPhase('seal-profile');
      const manifest = await writeWarmProfileManifest({
        profileDir: PROFILE_DIR,
        candidateSha: EXPECTED_SHA,
        runtimeProof: stabilized.runtimeProof,
        source: {
          backendVersion: identity.service.backendVersion,
          backendSha: identity.service.buildSha,
          frontendVersion,
          frontendSha,
          publicUrl: TODAY_URL,
          seededSnapshotId: seeded.snapshotId,
        },
      });
      if (!finalReleaseMachine) throw new Error('release_state_machine_missing');
      finalReleaseMachine.transition('R16_WARM_PROFILE_SEALED', {
        warmProfileArtifactId: manifest.artifactId,
      });
      await writeJson('version.json', {
        backendVersion: identity.service.backendVersion,
        backendSha: identity.service.buildSha,
        frontendVersion,
        frontendSha,
        seededSnapshotId: seeded.snapshotId,
        warmProfileArtifactId: manifest.artifactId,
      });
      markPhase('complete');
      await writeJson('diagnostics.json', await diagnostics('PASS'));
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
    await openCanonicalEvidence(page);
    if (MODE === 'profile') {
      const canonical = await selectCanonical1321FiveDay(page, {
        expectedSnapshotId: warmProfile.source.seededSnapshotId,
        onTransition: (event) => {
          if (!event.detail?.assumed) evidence.releaseStateLog.push(event);
        },
      });
      canonical.machine.transition('R16_WARM_PROFILE_SEALED', {
        warmProfileArtifactId: warmProfile.artifactId,
      });
      const result = {
        verdict: canonical.responseSnapshotId === warmProfile.source.seededSnapshotId
          && canonical.responseSnapshotId === canonical.uiSnapshotId
          ? 'PASS' : 'FAIL',
        candidateSha: EXPECTED_SHA,
        canonicalHorizon: canonical.canonicalHorizon,
        seededSnapshotId: canonical.responseSnapshotId,
        verifiedSnapshotHttpStatus: canonical.httpStatus,
        warmProfileArtifactId: warmProfile.artifactId,
        releaseStateLog: evidence.releaseStateLog,
      };
      if (result.verdict === 'PASS') {
        canonical.machine.transition('R17_PUBLIC_PRODUCT_ACCEPTED', {
          mode: 'independent_profile_reopen',
        });
      }
      await writeJson('acceptance.json', result);
      markPhase('complete');
      await writeJson('diagnostics.json', await diagnostics(result.verdict));
      if (result.verdict !== 'PASS') process.exitCode = 1;
      return;
    }
    const acceptanceCanonical = await selectCanonical1321FiveDay(page, {
      expectedSnapshotId: warmProfile.source.seededSnapshotId,
      onTransition: (event) => {
        if (!event.detail?.assumed) evidence.releaseStateLog.push(event);
      },
    });
    acceptanceCanonical.machine.transition('R16_WARM_PROFILE_SEALED', {
      warmProfileArtifactId: warmProfile.artifactId,
    });
    if (await page.evaluate(() => location.hash) !== '#today') {
      evidence.failures.push('canonical-today-deeplink');
    }
    if (await page.locator('[data-argus-control="market-instrument"]').count() !== 4) {
      evidence.failures.push('market-instrument-count');
    }

    for (const symbol of SYMBOLS) {
      for (const horizon of HORIZONS) {
        const record = await selectCombination(page, symbol, horizon);
        evidence.combinations.push({ symbol, horizon, ...record });
        if (!record.snapshotId || record.verification !== 'verified'
            || record.instrument !== symbol || record.canonicalHorizon !== horizon) {
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
      releaseStateLog: evidence.releaseStateLog,
      failures: evidence.failures,
    };
    if (result.verdict === 'PASS') {
      acceptanceCanonical.machine.transition('R17_PUBLIC_PRODUCT_ACCEPTED', {
        mode: 'full_public_acceptance',
      });
    }
    await writeJson('acceptance.json', result);
    await writeJson('console.json', evidence.console);
    await writeJson('network.json', evidence.network);
    await writeJson('computed-styles.json', evidence.computedStyles);
    await writeJson('version.json', {
      frontendVersion, frontendSha, backendVersion, backendSha,
    });
    markPhase('complete', result.verdict);
    await writeJson('diagnostics.json', await diagnostics(result.verdict));
    if (evidence.failures.length) process.exitCode = 1;
  } catch (error) {
    markPhase('failure', 'FAIL', sanitize(error?.message || error));
    const failure = {
      verdict: 'FAIL', todayProductStatus: 'NOT_FROZEN',
      testedAt: new Date().toISOString(), publicUrl: TODAY_URL,
      failures: [sanitize(error?.stack || error?.message || error)],
    };
    await writeJson('acceptance.json', failure);
    await writeJson('console.json', evidence.console);
    await writeJson('network.json', evidence.network);
    if (page) await screenshot(page, 'failure.png').catch(() => {});
    await writeJson('diagnostics.json', await diagnostics('FAIL'));
    console.error(`[argus-warm-profile] ${failure.failures[0]}`);
    process.exitCode = 1;
  } finally {
    await drainResponses(evidence);
    if (!contextClosed && context) await context.close().catch(() => {});
  }
}

await run();
