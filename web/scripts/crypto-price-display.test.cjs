'use strict';
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const assert = require('node:assert/strict');
const ts = require('typescript');
const compile = (source, file) => ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.React, esModuleInterop: true }, fileName: file,
}).outputText;
for (const ext of ['.ts', '.tsx']) require.extensions[ext] = (m, file) =>
  m._compile(compile(fs.readFileSync(file, 'utf8'), file), file);
const display = require('../src/domain/cryptoPriceDisplay.ts');
const authority = require('../src/domain/liveAuthority.ts');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const initialNow = Date.parse('2026-10-08T03:00:00Z');
let now = initialNow;
const fresh = { id: 'bitcoin', priceUsd: 70001, changePct: 1.25, volume: 120,
  date: '2026-10-08', source: 'coingecko', status: 'live',
  sourceTimestamp: new Date(now - 1000).toISOString(), receivedAt: new Date(now).toISOString(),
  realtimeEvidence: true, sourceTimeStatus: 'PRESENT' };
const coinbase = { ...fresh, priceUsd: 70002, source: 'coinbase', status: 'delayed',
  sourceTimestamp: null, date: null, realtimeEvidence: false, sourceTimeStatus: 'MISSING' };
const snapshot = (quote, provider = quote.source) => ({ provider, status: quote.status, quotes: [quote], asOf: quote.sourceTimestamp });
const select = (quote) => display.acceptCryptoDisplay({}, snapshot(quote), ['bitcoin']);
assert.equal(display.cryptoPriceDisplay(select(fresh).bitcoin, now).label, 'リアルタイム');
assert.equal(display.cryptoPriceDisplay(select(coinbase).bitcoin, now).label, '時刻未確認');
assert.equal(authority.cryptoQuoteDecisionUsable(coinbase, now), false);
for (const patch of [{ priceUsd: 0 }, { priceUsd: -1 }, { priceUsd: NaN },
  { priceUsd: Infinity }, { priceUsd: '70000' }, { status: 'mock' },
  { status: 'unavailable' }, { source: 'unknown' }, { id: 'ethereum' }]) {
  assert.deepEqual(select({ ...fresh, ...patch }), {});
}
assert.deepEqual(display.acceptCryptoDisplay({}, snapshot(fresh, 'coinbase'), ['bitcoin']), {});
const expired = { ...fresh, sourceTimestamp: new Date(now - 300001).toISOString() };
assert.equal(display.cryptoPriceDisplay(select(expired).bitcoin, now).label, '保存価格');
assert.equal(authority.cryptoQuoteDecisionUsable(expired, now), false);
for (const stamp of [null, 'bad', new Date(now + 1000).toISOString()]) {
  assert.equal(display.cryptoPriceDisplay(select({ ...fresh, sourceTimestamp: stamp }).bitcoin, now).label, '時刻未確認');
}
const saved = display.acceptCryptoDisplay(select(fresh), snapshot({ ...fresh, status: 'mock', priceUsd: 1 }), ['bitcoin']);
assert.equal(saved.bitcoin.quote.priceUsd, 70001);
assert.equal(saved.bitcoin.retained, true);
assert.deepEqual(display.acceptCryptoDisplay(saved, snapshot(coinbase), ['ethereum']), {});
assert.equal(display.cryptoDisplayForAsset({ symbol: 'BTC', memo: 'coingecko:missing-id' }, select(coinbase)).quote.priceUsd, 70002);
assert.equal(display.cryptoPriceDisplay(select({ ...coinbase, changePct: NaN }).bitcoin, now).changePct, null);

// Render the actual card header without opening a second quote acquisition.
const summaryFile = path.resolve(__dirname, '../src/components/assetDesk/AssetDecisionSummary.tsx');
const summaryModule = new Module(summaryFile, module);
summaryModule.filename = summaryFile; summaryModule.paths = module.paths;
const summaryRequire = summaryModule.require.bind(summaryModule);
summaryModule.require = name => name.endsWith('/useDecisionEvidence')
  ? { useTachibanaLiveDocument: () => null }
  : name.endsWith('/useAnalystTargets')
    ? { useAnalystTargetState: () => ({ items: {}, availability: {}, loading: false }) }
    : summaryRequire(name);
const originalLoad = Module._load;
Module._load = function(name, ...args) {
  if (name.endsWith('/useAnalystTargets')) return { useAnalystTargetState: () => ({ items: {}, availability: {}, loading: false }) };
  return originalLoad.call(this, name, ...args);
};
try { summaryModule._compile(compile(fs.readFileSync(summaryFile, 'utf8'), summaryFile), summaryFile); }
finally { Module._load = originalLoad; }
const d = { asset: { market: 'CRYPTO', symbol: 'BTC' }, genre: 'crypto',
  strat: { status: 'mock' }, decisionFirst: { symbol: 'BTC', name: 'Bitcoin',
    priceText: '—', dataStatus: '未取得', quoteTruth: null },
  cryptoDisplayQuote: select(coinbase).bitcoin };
const before = JSON.stringify(d);
const render = patch => {
  const original = Date.now; Date.now = () => initialNow;
  try { return renderToStaticMarkup(React.createElement(summaryModule.exports.AssetDecisionSummary,
    { d: { ...d, ...patch }, open: false, onToggle() {} })); }
  finally { Date.now = original; }
};
const html = render({});
for (const fact of ['$70,002', 'Coinbase', '価格時刻不明', '受信', '時刻未確認']) assert.ok(html.includes(fact), fact);
for (const fact of ['価格未取得', 'リアルタイム']) assert.ok(!html.includes(fact), fact);
assert.ok(render({ cryptoRefreshFailed: true }).includes('更新失敗・保存価格'));
assert.ok(render({ cryptoDisplayQuote: undefined }).includes('価格未取得'));
assert.equal(JSON.stringify(d), before, 'render cannot renew decision evidence');

// Exercise the real shared hook: fallback, fresh read, expiry, failed/partial
// refresh and remount retain display only; consumers still share one read.
(async () => {
  const originalFetch = global.fetch, originalWindow = global.window, originalDocument = global.document;
  const originalNow = Date.now;
  const subscriptions = [], expiryTasks = new Map();
  let interval, calls = 0, nextId = 0, response = snapshot(coinbase), failure = false;
  Date.now = () => now;
  global.window = { setTimeout, clearTimeout };
  global.document = { hidden: false };
  global.fetch = async () => {
    calls++;
    if (failure) throw new Error('offline');
    return { ok: true, json: async () => response };
  };
  const hookFile = path.resolve(__dirname, '../src/hooks/useCryptoWatchlist.ts');
  const m = new Module(hookFile, module); m.filename = hookFile; m.paths = module.paths;
  const nativeRequire = m.require.bind(m);
  m.require = name => name === 'react'
    ? { useSyncExternalStore: (subscribe, snapshotFn) => {
      subscriptions.push(subscribe(() => {})); return snapshotFn();
    } }
    : name.endsWith('/pollingPolicy') ? {
      GUARD_VISIBLE_MS: 300000, isPageVisible: () => true,
      scheduleVisibleInterval: read => { interval = read; return () => {}; },
      subscribeInitialVisibleRead: () => () => {},
    } : name.endsWith('/liveAuthority') ? { ...authority,
      scheduleLiveAuthorityExpiry: (stamp, kind, expire) => authority.scheduleLiveAuthorityExpiry(stamp, kind, expire, {
        now: () => now, setTimeout: (callback, delay) => { const id = ++nextId; expiryTasks.set(id, { callback, at: now + delay }); return id; },
        clearTimeout: id => expiryTasks.delete(id),
      }) } : nativeRequire(name);
  m._compile(compile(fs.readFileSync(hookFile, 'utf8').replaceAll('import.meta.env',
    '({VITE_ARGUS_BACKEND_URL:"https://quotes.test"})'), hookFile), hookFile);
  const read = () => m.exports.useCryptoWatchlist(['bitcoin']);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  try {
    read(); read(); await settle();
    let state = read();
    assert.equal(calls, 1); assert.deepEqual(state.byId, {});
    assert.equal(state.displayById.bitcoin.quote.priceUsd, 70002);
    assert.equal(state.authority, 'unavailable');
    response = snapshot(fresh); interval(); interval(); await settle();
    state = read();
    assert.equal(calls, 2); assert.equal(state.byId.bitcoin.decisionUsable, true);
    assert.equal(state.displayById.bitcoin.quote.decisionUsable, false);
    now += 300001;
    for (const task of [...expiryTasks.values()]) if (task.at <= now) task.callback();
    state = read();
    assert.deepEqual(state.byId, {}); assert.equal(state.authority, 'expired');
    assert.equal(state.displayById.bitcoin.quote.priceUsd, 70001);
    assert.equal(display.cryptoPriceDisplay(state.displayById.bitcoin, now).label, '保存価格');
    failure = true; interval(); interval(); await settle();
    state = read();
    assert.equal(calls, 3); assert.deepEqual(state.byId, {});
    assert.equal(state.authority, 'refresh_failed');
    assert.equal(state.displayById.bitcoin.quote.sourceTimestamp, fresh.sourceTimestamp);
    failure = false; response = snapshot({ ...fresh, status: 'mock', priceUsd: 1 });
    interval(); await settle();
    state = read(); assert.deepEqual(state.byId, {});
    assert.equal(state.displayById.bitcoin.quote.priceUsd, 70001);
    subscriptions.splice(0).forEach(stop => stop());
    state = read(); assert.deepEqual(state.byId, {});
    assert.equal(state.displayById.bitcoin.retained, true);
    await settle();
    const intel = fs.readFileSync(path.resolve(__dirname, '../src/hooks/useAssetIntel.ts'), 'utf8');
    assert.ok(!intel.includes('displayById'), 'display quotes cannot feed valuation/SDA');
    const desk = fs.readFileSync(path.resolve(__dirname, '../src/components/assetDesk/AssetDeskList.tsx'), 'utf8');
    assert.ok(desk.includes('cryptoDisplayForAsset(a, intel.cryptoWatch.displayById)'));
    assert.ok(desk.includes('intel.cryptoWatch.byId[id]'), 'strategy still uses strict evidence');
    console.log('Crypto actual shared hook/card: real fallback, saved/partial/failure/expiry, mock rejection and authority isolation PASS');
  } finally {
    subscriptions.forEach(stop => stop()); Date.now = originalNow;
    global.fetch = originalFetch; global.window = originalWindow; global.document = originalDocument;
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
