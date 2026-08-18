import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';
import {
  RELEASE_ENGINE_VERSION,
  evaluateBusinessSnapshotSet,
  evaluateInfrastructureReadiness,
  fetchBusinessSnapshots,
  loadSnapshotContract,
  snapshotIdentity,
  triggerBusinessSnapshots,
  validateSnapshotContract,
} from './release-state-machine.mjs';
import { selectCanonical1321FiveDay } from './canonical-snapshot-selection.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((rows, value, index, all) => {
  if (value.startsWith('--')) rows.push([value.slice(2), all[index + 1]]);
  return rows;
}, []));
const runNumber = Number(args.run ?? 0);
const outputPath = path.resolve(args.out ?? `../artifacts/full-release-simulation-${runNumber}.json`);
const candidateSha = process.env.ARGUS_SIM_EXPECTED_SHA ?? '';
const distDir = path.resolve(process.env.ARGUS_SIM_DIST ?? 'dist');
const backendPort = Number(process.env.ARGUS_SIM_BACKEND_PORT ?? 4199);
const frontendPort = Number(process.env.ARGUS_SIM_FRONTEND_PORT ?? 4173);
const backendUrl = `http://127.0.0.1:${backendPort}`;
const publicUrl = `http://127.0.0.1:${frontendPort}/argus/`;
const adminToken = 'simulation-release-token';
const contract = validateSnapshotContract(loadSnapshotContract(
  new URL('../../release/v13-snapshot-readiness-contract.json', import.meta.url),
));

if (!Number.isInteger(runNumber) || runNumber < 1 || runNumber > 2) {
  throw new Error('full_release_simulation_run_must_be_1_or_2');
}
if (!/^[0-9a-f]{40}$/.test(candidateSha)) throw new Error('candidate_sha_invalid');
if (!fs.existsSync(path.join(distDir, 'index.html'))) throw new Error('candidate_dist_missing');

const sorted = (value) => {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
      .map(([key, child]) => [key, sorted(child)]));
  }
  return value;
};
const canonical = (value) => JSON.stringify(sorted(value));
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const portableNumber = (value) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const text = value.toFixed(8).replace(/0+$/, '').replace(/\.$/, '');
  return text === '-0' || text === '' ? '0' : text;
};

const payloadFor = (row, datasetHash, generatedAt) => {
  const bars = [
    { date: '2026-08-14', open: 100, high: 103, low: 99, close: 102,
      volume: 1000, adjusted: false, availableFrom: '2026-08-14', ma: {},
      bollinger: null, rsi14: null, macd: null, atr14: null, sar: null,
      ichimoku: { conversion: null, base: null, spanA: null, spanB: null },
      volumeRatio20: null },
    { date: '2026-08-17', open: 102, high: 105, low: 101, close: 104,
      volume: 1100, adjusted: false, availableFrom: '2026-08-17', ma: {},
      bollinger: null, rsi14: null, macd: null, atr14: null, sar: null,
      ichimoku: { conversion: null, base: null, spanA: null, spanB: null },
      volumeRatio20: null },
  ];
  return {
    schemaVersion: 'chart-intelligence-phase2-v1',
    methodVersion: 'chart-intelligence-phase2-v2-pit-bound',
    reportId: `simulation-${row.instrument}`,
    symbol: row.instrument,
    market: row.market,
    displayNameJa: row.instrument,
    timeframe: 'daily',
    status: 'complete',
    missingReasons: [],
    source: row.market === 'JP' ? 'jquants' : 'twelvedata',
    asOf: generatedAt,
    periodEnd: generatedAt.slice(0, 10),
    automaticAiCalls: 0,
    costPolicyMode: 'automatic-ai-zero',
    instrumentMetadata: {
      instrumentId: `${row.market}:${row.instrument}:ETF`,
      symbol: row.instrument, market: row.market, assetType: 'ETF',
      displayNameJa: row.instrument, source: 'simulation-provider-cache',
      availableFrom: '2026-08-17', observedAt: generatedAt, revision: 1,
    },
    indicators: { status: 'complete', missingReasons: [], bars },
    zones: [], turningPoints: [], reactionAnomalies: [], relationshipBreaks: [],
    eventMarkers: [], valuationLevels: [], critique: [], scenarios: [],
    persistence: { stateHash: datasetHash, verificationStatus: 'verified',
      lastVerifiedReadBackAt: generatedAt },
    marketReplay: {
      cacheStatus: 'updated',
      contexts: Object.fromEntries(['1', '5', '20'].map((horizon) => [horizon, {
        datasetHash, asOf: generatedAt,
        methodVersion: 'market-context-replay-v3-pit-bound',
      }])),
    },
    relativeStrength: {}, rotationMap: [],
    noteJa: 'simulation fixture',
  };
};

const buildSnapshot = (row, releaseBinding, generatedAt, index) => {
  const datasetHash = sha256(`simulation-dataset:${row.instrument}:${runNumber}`);
  const payload = payloadFor(row, datasetHash, generatedAt);
  const material = payload.indicators.bars.map((bar) => ({
    date: String(bar.date ?? ''), open: portableNumber(bar.open),
    high: portableNumber(bar.high), low: portableNumber(bar.low),
    close: portableNumber(bar.close), volume: portableNumber(bar.volume),
    availableFrom: String(bar.availableFrom ?? ''),
  }));
  const snapshot = {
    schemaVersion: 'argus-verified-view-snapshot-v1',
    snapshotId: '',
    kind: row.kind,
    instrument: row.instrument,
    horizon: row.horizon,
    datasetHash,
    payloadHash: sha256(canonical(material)),
    methodVersion: 'verified-chart-view-v1:chart-intelligence-phase2-v2-pit-bound:' +
      'market-context-replay-v3-pit-bound',
    asOf: generatedAt,
    generatedAt,
    verifiedAt: generatedAt,
    quality: 'live',
    sourceStatus: { chart: 'complete', indicators: 'complete', replay: 'updated',
      durableReadBack: 'verified' },
    verificationStatus: 'verified',
    payload,
    releaseBinding,
  };
  const identity = {
    schemaVersion: snapshot.schemaVersion, kind: snapshot.kind,
    instrument: snapshot.instrument, horizon: snapshot.horizon,
    datasetHash: snapshot.datasetHash, payloadHash: snapshot.payloadHash,
    methodVersion: snapshot.methodVersion, asOf: snapshot.asOf,
    generatedAt: snapshot.generatedAt, verifiedAt: snapshot.verifiedAt,
    quality: snapshot.quality, sourceStatus: snapshot.sourceStatus,
    verificationStatus: snapshot.verificationStatus,
    releaseBinding: snapshot.releaseBinding,
  };
  snapshot.snapshotId = `vs-${sha256(canonical(identity)).slice(0, 32)}`;
  snapshot.simulationOrdinal = index;
  return snapshot;
};

const readBody = async (request) => {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
};
const json = (response, status, value, headers = {}) => {
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': '*',
    'Cache-Control': 'no-store',
    ...headers,
  });
  response.end(JSON.stringify(value));
};

const fixture = { snapshots: new Map(), trigger: null };
const backendServer = http.createServer(async (request, response) => {
  if (request.method === 'OPTIONS') {
    response.writeHead(204, { 'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' });
    response.end();
    return;
  }
  const url = new URL(request.url, backendUrl);
  if (url.pathname === '/healthz') {
    json(response, 200, { status: 'ok', backendVersion: '13.4.13', buildSha: candidateSha });
    return;
  }
  if (url.pathname === '/readyz') {
    json(response, 200, { status: 'ready', ready: true, reasonCode: 'READY',
      backendVersion: '13.4.13', buildSha: candidateSha });
    return;
  }
  if (url.pathname === '/api/argus/admin/missions/tick' && request.method === 'POST') {
    if (request.headers['x-argus-admin-token'] !== adminToken) {
      json(response, 401, { status: 'failed', error: 'unauthorized' }); return;
    }
    const body = await readBody(request);
    if (body.releaseSnapshotSeed !== true || body.expectedBuildSha !== candidateSha) {
      json(response, 400, { status: 'failed', error: 'invalid_release_seed' }); return;
    }
    const triggeredAt = new Date().toISOString();
    const generatedAt = new Date(Date.parse(triggeredAt) + 1).toISOString();
    const releaseBinding = { expectedBuildSha: candidateSha,
      producerTriggerId: body.runId, triggeredAt };
    fixture.snapshots.clear();
    contract.snapshots.forEach((row, index) => {
      fixture.snapshots.set(row.identity,
        buildSnapshot(row, releaseBinding, generatedAt, index));
    });
    fixture.trigger = releaseBinding;
    json(response, 200, {
      ok: true, status: 'completed', schemaVersion: 'argus-release-snapshot-seed-v1',
      producer: 'scanner._precompute_verified_market_view',
      producerTriggerId: body.runId, expectedBuildSha: candidateSha,
      triggeredAt, completedAt: generatedAt, snapshotExpected: 12, snapshotReady: 12,
      snapshots: [...fixture.snapshots.values()].map((snapshot) => ({
        identity: snapshotIdentity(snapshot), market: contract.snapshots.find(
          (row) => row.identity === snapshotIdentity(snapshot)).market,
        instrument: snapshot.instrument, horizon: snapshot.horizon,
        snapshotId: snapshot.snapshotId, generatedAt: snapshot.generatedAt,
        verificationStatus: snapshot.verificationStatus,
        releaseBinding: snapshot.releaseBinding,
      })),
      persistence: { verified: true, readBackVerified: true },
      recoveryAuthorityChanged: false,
    });
    return;
  }
  if (url.pathname === '/api/argus/chart-intelligence') {
    const identity = `market-chart:${url.searchParams.get('symbol')}:` +
      `${url.searchParams.get('horizon')}`;
    const snapshot = fixture.snapshots.get(identity);
    if (!snapshot) { json(response, 503, { status: 'not_ready', reason: 'verified_snapshot_missing' }); return; }
    json(response, 200, snapshot, {
      ETag: `"${snapshot.snapshotId}"`,
      'X-ARGUS-Compute-Mode': 'read-only',
      'X-ARGUS-Snapshot-Id': snapshot.snapshotId,
    });
    return;
  }
  // Support surfaces are deliberately data-gated in the hermetic simulation.
  // A non-200 response exercises the product's existing fail-closed hook paths;
  // returning a made-up 200 shape would be a false business-data fixture.
  json(response, 503, { status: 'DATA_GATED', error: 'simulation_data_gated',
    backendVersion: '13.4.13', buildSha: candidateSha, automaticAiCalls: 0 });
});

const mime = new Map([
  ['.html', 'text/html; charset=utf-8'], ['.js', 'text/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'], ['.json', 'application/json'],
  ['.svg', 'image/svg+xml'], ['.webmanifest', 'application/manifest+json'],
  ['.map', 'application/json'],
]);
const frontendServer = http.createServer((request, response) => {
  const url = new URL(request.url, publicUrl);
  let relative = decodeURIComponent(url.pathname).replace(/^\/argus\/?/, '');
  if (!relative || !path.extname(relative)) relative = relative || 'index.html';
  let target = path.resolve(distDir, relative);
  if (!target.startsWith(`${distDir}${path.sep}`) && target !== path.join(distDir, 'index.html')) {
    response.writeHead(403); response.end(); return;
  }
  if (!fs.existsSync(target) || fs.statSync(target).isDirectory()) target = path.join(distDir, 'index.html');
  response.writeHead(200, { 'Content-Type': mime.get(path.extname(target)) ?? 'application/octet-stream',
    'Cache-Control': target.endsWith('index.html') ? 'no-store' : 'public, max-age=60' });
  fs.createReadStream(target).pipe(response);
});

const listen = (server, port) => new Promise((resolve, reject) => {
  server.once('error', reject); server.listen(port, '127.0.0.1', resolve);
});
const close = (server) => new Promise((resolve) => server.close(resolve));
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), `argus-v13-sim-${runNumber}-`));
const evidence = {
  schemaVersion: 'argus-v13-full-release-simulation-v1',
  engineVersion: RELEASE_ENGINE_VERSION,
  runNumber,
  status: 'failure',
  candidateSha,
  candidateDist: distDir,
  initial: { snapshotReady: 0, snapshotExpected: 12 },
  stateLog: [], consoleErrors: [],
};
let context;

try {
  await listen(backendServer, backendPort);
  const health = await (await fetch(`${backendUrl}/healthz`)).json();
  const ready = await (await fetch(`${backendUrl}/readyz`)).json();
  evidence.infrastructure = evaluateInfrastructureReadiness({
    backendHealth: health, backendReady: ready, expectedBuildSha: candidateSha,
    processStable: true, crashLoop: false, oomKilled: false, storageValid: true,
    restoreOutcome: 'test_mode', infraSnapshots: [],
  }, contract);
  assert.equal(evidence.infrastructure.pass, true);
  assert.equal(fixture.snapshots.size, 0, 'infrastructure must pass with business state at 0/12');

  await listen(frontendServer, frontendPort);
  const index = await (await fetch(publicUrl, { cache: 'no-store' })).text();
  assert.match(index, new RegExp(candidateSha));
  evidence.frontendDeploymentEquivalent = { status: 'pass', publicUrl };

  context = await chromium.launchPersistentContext(profileDir, { headless: true,
    viewport: { width: 1280, height: 900 }, serviceWorkers: 'allow' });
  let page = context.pages()[0] ?? await context.newPage();
  page.on('console', (message) => {
    if (message.type() === 'error') evidence.consoleErrors.push(message.text());
  });
  await page.goto(publicUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.waitForFunction((sha) => globalThis.__ARGUS_BUILD_SHA__ === sha,
    candidateSha, { timeout: 30_000 });
  assert.equal(await page.evaluate(() => globalThis.__ARGUS_PRODUCT_VERSION__), 'v13.5');
  evidence.identitiesConverged = true;

  const producerTriggerId = `full-release-simulation-${runNumber}-${candidateSha.slice(0, 12)}`;
  evidence.trigger = await triggerBusinessSnapshots({
    baseUrl: backendUrl, adminToken, contract, expectedBuildSha: candidateSha,
    producerTriggerId,
  });
  assert.equal(fixture.snapshots.size, 12);

  const canonicalResult = await selectCanonical1321FiveDay(page, {
    timeout: 90_000,
    onTransition: (event) => {
      if (!event.detail?.assumed) evidence.stateLog.push(event);
    },
  });
  assert.equal(canonicalResult.responseSnapshotId, canonicalResult.uiSnapshotId);
  evidence.canonical = {
    responseSnapshotId: canonicalResult.responseSnapshotId,
    uiSnapshotId: canonicalResult.uiSnapshotId,
    instrument: '1321',
    horizon: '5D',
  };

  await page.waitForFunction(async () => {
    const registration = await navigator.serviceWorker.getRegistration();
    return !!registration?.active && !!navigator.serviceWorker.controller;
  }, null, { timeout: 30_000 });
  const runtimeProof = await page.evaluate(async () => {
    const databases = await indexedDB.databases();
    const registration = await navigator.serviceWorker.getRegistration();
    return {
      databaseNames: databases.map((row) => row.name).filter(Boolean),
      serviceWorkerScript: registration?.active?.scriptURL ?? null,
      frontendSha: globalThis.__ARGUS_BUILD_SHA__,
      productVersion: globalThis.__ARGUS_PRODUCT_VERSION__,
    };
  });
  assert.ok(runtimeProof.databaseNames.includes('argus-verified-snapshots'));
  assert.equal(runtimeProof.frontendSha, candidateSha);
  assert.match(runtimeProof.serviceWorkerScript, /sw\.js$/);
  evidence.warmProfileSeal = { status: 'pass', ...runtimeProof };

  await context.close(); context = null;
  context = await chromium.launchPersistentContext(profileDir, { headless: true,
    viewport: { width: 1280, height: 900 }, serviceWorkers: 'allow' });
  page = context.pages()[0] ?? await context.newPage();
  page.on('console', (message) => {
    if (message.type() === 'error') evidence.consoleErrors.push(message.text());
  });
  await page.goto(publicUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.waitForFunction((snapshotId) => document.querySelector(
    '[data-argus-contract="canonical-market-snapshot-v1"]',
  )?.getAttribute('data-canonical-snapshot-id') === snapshotId,
  canonicalResult.responseSnapshotId, { timeout: 90_000 });
  evidence.independentProfileReopen = { status: 'pass' };

  const snapshots = await fetchBusinessSnapshots({ baseUrl: backendUrl, contract });
  evidence.businessSnapshots = evaluateBusinessSnapshotSet({
    contract, observed: snapshots, expectedBuildSha: candidateSha,
    producerTriggerId,
  });
  assert.equal(evidence.businessSnapshots.pass, true);
  assert.deepEqual(evidence.businessSnapshots.expectedSet,
    evidence.businessSnapshots.observedSet);

  const brand = await page.locator('.shell__brand').innerText();
  assert.match(brand, /A\.R\.G\.U\.S\.\s+Pro/);
  assert.match(brand, /A\.R\.G\.U\.S\.\s+Pro\s+v13\.5/);
  for (const label of ['Today', 'Holdings / Watchlist', 'Notifications', 'Settings']) {
    assert.ok(await page.getByText(label, { exact: true }).count() > 0, label);
  }
  evidence.publicProductAcceptance = { status: 'pass', brand,
    surfaces: ['Today', 'Holdings / Watchlist', 'Notifications', 'Settings'] };

  const invalidatingConsoleErrors = evidence.consoleErrors.filter((message) =>
    !/Failed to load resource.*(429|503)/i.test(message));
  assert.deepEqual(invalidatingConsoleErrors, []);
  evidence.status = 'pass';
  evidence.completedAt = new Date().toISOString();
} catch (error) {
  evidence.failure = { name: error.name, message: error.message, stack: error.stack };
  throw error;
} finally {
  if (context) await context.close().catch(() => {});
  await Promise.all([
    frontendServer.listening ? close(frontendServer).catch(() => {}) : Promise.resolve(),
    backendServer.listening ? close(backendServer).catch(() => {}) : Promise.resolve(),
  ]);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(evidence, null, 2)}\n`);
  fs.rmSync(profileDir, { recursive: true, force: true });
}

console.log(`FULL_RELEASE_SIMULATION_${runNumber}=PASS`);
