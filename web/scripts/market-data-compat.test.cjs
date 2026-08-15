const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');

function loadBundled(entry) {
  const result = buildSync({
    entryPoints: [entry],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    target: 'node20',
    write: false,
    logLevel: 'silent',
  });
  const filename = `${entry}.compat.cjs`;
  const loaded = new Module(filename, module);
  loaded.filename = filename;
  loaded.paths = Module._nodeModulePaths(path.dirname(entry));
  loaded._compile(result.outputFiles[0].text, filename);
  return loaded.exports;
}

const root = path.resolve(__dirname, '..');
const live = loadBundled(path.join(root, 'src/domain/liveQuote.ts'));
const watch = loadBundled(path.join(root, 'src/domain/watchQuoteTruth.ts'));
const nowMs = Date.UTC(2026, 6, 28, 3, 0, 0);
const options = { symbol: 'SPY', instrumentType: 'ETF', provider: 'moomoo-rt', nowMs };

const oldBackend = live.normalizeLiveQuote({
  symbol: 'SPY',
  price: 700,
  changeAbs: 1,
  changePct: 0.1,
  status: 'live',
  date: '2026-07-28',
  provider: 'moomoo-rt',
}, options);
assert.equal(oldBackend.delayClass, 'UNKNOWN');
assert.equal(oldBackend.session, 'UNKNOWN');
assert.equal(oldBackend.entitlement, 'unknown');
assert.equal(oldBackend.ageSec, null);

const declaredWithoutProof = live.normalizeLiveQuote({
  price: 700,
  status: 'live',
  delayClass: 'LIVE',
  provider: 'moomoo-rt',
}, options);
assert.equal(declaredWithoutProof.delayClass, 'UNKNOWN');

const proven = live.normalizeLiveQuote({
  price: 700,
  status: 'live',
  delayClass: 'LIVE',
  realtimeEvidence: true,
  exchangeTs: new Date(nowMs - 30_000).toISOString(),
  provider: 'moomoo-rt',
}, options);
assert.equal(proven.delayClass, 'LIVE');
assert.equal(proven.ageSec, 30);
assert.equal(proven.session, 'UNKNOWN');
assert.equal(proven.entitlement, 'unknown');

const futureTimestamp = live.normalizeLiveQuote({
  price: 700,
  status: 'live',
  delayClass: 'LIVE',
  realtimeEvidence: true,
  exchangeTs: new Date(nowMs + 1_000).toISOString(),
  provider: 'moomoo-rt',
}, options);
assert.equal(futureTimestamp.ageSec, null);
assert.equal(futureTimestamp.delayClass, 'UNKNOWN');

const stale = live.normalizeLiveQuote({
  price: 700,
  status: 'live',
  realtimeEvidence: true,
  exchangeTs: new Date(nowMs - 900_000).toISOString(),
  provider: 'moomoo-rt',
}, options);
assert.equal(stale.delayClass, '15m');
assert.equal(stale.ageSec, 900);

const staleCache = live.normalizeLiveQuote({
  price: 700,
  status: 'delayed',
  delayClass: 'UNKNOWN',
  realtimeEvidence: false,
  date: '2026-07-27',
  provider: 'moomoo-rt',
}, options);
assert.equal(staleCache.delayClass, 'UNKNOWN');
assert.equal(staleCache.ageSec, null);

const offline = live.normalizeLiveQuote({
  price: null,
  status: 'mock',
  provider: 'offline',
}, options);
assert.equal(offline.delayClass, 'OFFLINE');
assert.equal(offline.price, null);
assert.equal(offline.change, null);

const malformed = live.normalizeLiveQuote({
  price: 700,
  status: 'live',
  exchangeTs: 'not-a-timestamp',
  provider: 'moomoo-rt',
}, options);
assert.equal(malformed.sourceTimestamp, null);
assert.equal(malformed.ageSec, null);
assert.equal(malformed.delayClass, 'UNKNOWN');

const normalizedSnapshot = watch.normalizeWatchSnapshot({
  status: 'live',
  asOf: '2026-07-28',
  provider: 'moomoo-rt',
  stocks: [{
    symbol: 'SPY',
    name: 'SPY',
    price: 700,
    changeAbs: 1,
    changePct: 0.1,
    volume: 1,
    date: '2026-07-28',
    status: 'live',
  }],
});
assert.equal(normalizedSnapshot.status, 'unknown');
assert.equal(normalizedSnapshot.stocks[0].delayClass, 'UNKNOWN');
assert.equal(normalizedSnapshot.stocks[0].quoteTruth.instrumentType, 'ETF');

console.log('market-data-compat.test: ok');
