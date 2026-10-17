'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const crypto = require('node:crypto').webcrypto;
const source = fs.readFileSync('src/lib/watchlistAutoSync.ts', 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
class Store {
  constructor() { this.data = new Map(); this.fail = false; this.removeFails = false; }
  get length() { return this.data.size; }
  key(n) { return [...this.data.keys()][n] ?? null; }
  getItem(k) { return this.data.get(k) ?? null; }
  setItem(k, v) { if (this.fail) throw Error('quota'); this.data.set(k, v); }
  removeItem(k) { if (this.removeFails) throw Error('quota'); this.data.delete(k); }
}
function setup(store = new Store()) {
  const exports = {};
  vm.runInNewContext(compiled, { exports, localStorage: store, crypto, Date, Event, AbortSignal,
    setTimeout, clearTimeout, setInterval, clearInterval, console });
  return { store, api: exports };
}
const a = { id: 'jp-synthetic', market: 'JP', symbol: '1234', enabled: true,
  displayName: '検査用', quantity: 500, avgCost: 999, memo: 'must not upload', privateExtension: { cash: 9999 } };
const b = { id: 'us-synthetic', market: 'US', symbol: 'TEST', enabled: true, displayName: '検査用米国' };
const cryptoAsset = { market: 'CRYPTO', symbol: 'BTC', enabled: true, memo: 'coingecko:bitcoin' };
const fund = { market: 'CORE', symbol: 'FUND-A', enabled: true, quantity: 123 };
const locks = { request: async (name, opts, fn) => { assert.equal(name, 'argus-membership-send-v1'); return fn({}); } };
const version = 'a'.repeat(40);
function pending(store) { return [...store.data.keys()].filter(k => k.startsWith('argus.watchlist-pending.v1.')); }
function edit(api, store, before, after) {
  const key = api.stageRegistrationChanges(before, after);
  store.setItem('argus.assets.v1', JSON.stringify(after));
  api.commitRegistrationChanges(key);
  return key;
}
function response(body, status = 200) { return { ok: status >= 200 && status < 300, status, json: async () => body }; }
function transport({ intercept, failWrite = false, conflictOnce = false, badReceipt = false } = {}) {
  const writes = []; let conflict = conflictOnce;
  const fetcher = async (url, init) => {
    const body = JSON.parse(init.body);
    if (url.endsWith('watchlist-membership')) return response({ status: 'ok', version, membership: { members: [b] } });
    writes.push(body);
    if (intercept) await intercept(body);
    if (failWrite) throw Error('offline');
    if (conflict) { conflict = false; return response({ status: 'conflict' }, 409); }
    return response({ ok: true, status: 'synced', version,
      batchId: badReceipt ? 'wrong' : body.batchId });
  };
  return { fetcher, writes };
}
(async () => {
  {
    const { api, store } = setup();
    store.setItem('argus.assets.v1', JSON.stringify([a, fund, cryptoAsset]));
    const net = transport();
    await api.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher: net.fetcher, locks });
    assert.equal(net.writes.length, 0, 'startup/defaults/empty outbox never upload');
    assert.equal(api.stageRegistrationChanges([fund], [{ ...fund, quantity: 555 }]), null, 'fund/holding changes stay local');
    assert.equal(api.stageRegistrationChanges([a], [{ ...a, quantity: 111, avgCost: 222, memo: 'changed' }]), null);
    edit(api, store, [a, fund, cryptoAsset], [a, fund, cryptoAsset, b]);
    await api.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher: net.fetcher, locks });
    assert.equal(net.writes.length, 1);
    assert.equal(net.writes[0].changes.length, 1, 'only explicit addition, not complete old list');
    const raw = JSON.stringify(net.writes);
    for (const field of ['quantity', 'avgCost', 'memo', 'privateExtension', 'cash', 'FUND-A']) assert.equal(raw.includes(field), false, field);
    assert.equal(pending(store).length, 0);
    assert.equal(JSON.parse(store.getItem('argus.assets.v1'))[0].quantity, 500);
  }
  {
    const { api, store } = setup();
    const key = edit(api, store, [a, b], [b]);
    const raw = store.getItem(key);
    const net = transport({ failWrite: true });
    await api.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher: net.fetcher, locks });
    assert.equal(store.getItem(key), raw, 'uncertain save retains the exact batch id for retry');
    const restarted = setup(store).api;
    const retry = transport({ conflictOnce: true });
    await restarted.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher: retry.fetcher, locks });
    assert.equal(retry.writes.length, 2);
    assert.equal(retry.writes[0].batchId, net.writes[0].batchId);
    assert.equal(retry.writes[0].batchId, retry.writes[1].batchId);
    assert.equal(pending(store).length, 0);
    assert.equal(retry.writes[0].changes[0].action, 'remove');
  }
  {
    const { api, store } = setup();
    edit(api, store, [a], [a, b]);
    const net = transport({ intercept: body => {
      if (body.changes[0].action === 'add') edit(api, store, [a, b], [a]);
    } });
    await api.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher: net.fetcher, locks });
    assert.deepEqual(net.writes.map(w => w.changes[0].action), ['add', 'remove'], 'edit in flight remains pending after earlier ack');
    assert.equal(pending(store).length, 0);
  }
  {
    const { api, store } = setup();
    edit(api, store, [a], [a, b]);
    // Restore is not an explicit removal of the queued addition.
    store.setItem('argus.assets.v1', JSON.stringify([a]));
    const net = transport();
    await api.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher: net.fetcher, locks });
    assert.equal(net.writes.length, 0);
    assert.equal(pending(store).length, 1, 'restore mismatch holds original intent rather than discarding or guessing');
  }
  for (const failure of ['auth', 'read', 'receipt', 'quota']) {
    const { api, store } = setup();
    edit(api, store, [a], [a, b]);
    const net = transport({ badReceipt: failure === 'receipt' });
    const fetcher = failure === 'auth' || failure === 'read'
      ? async () => response({ status: 'failed' }, failure === 'auth' ? 401 : 503) : net.fetcher;
    store.removeFails = failure === 'quota';
    await api.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher, locks });
    assert.equal(pending(store).length, 1, failure + ' never acknowledges or drops a pending edit');
  }
  {
    const { api, store } = setup();
    store.setItem('argus.assets.v1', JSON.stringify([a]));
    store.fail = true;
    assert.throws(() => api.stageRegistrationChanges([a], [a, b]));
    assert.equal(pending(store).length, 0, 'queue persistence failure prevents proceeding to local asset save');
  }
  {
    const { api, store } = setup();
    api.stageRegistrationChanges([a], [a, b]);
    store.setItem('argus.assets.v1', JSON.stringify([a]));
    const net = transport();
    await api.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher: net.fetcher, locks });
    assert.equal(net.writes.length, 0, 'crash before local commit cannot upload staged intent');
    store.setItem('argus.assets.v1', JSON.stringify([a, b]));
    await api.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher: net.fetcher, locks });
    assert.equal(net.writes.length, 1, 'crash after local commit recovers matching staged intent');
  }
  {
    const { api, store } = setup();
    edit(api, store, [], [cryptoAsset]);
    const net = transport();
    await api.flushWatchlistChanges('https://example.invalid', '', { storage: store, fetcher: net.fetcher, locks });
    assert.equal(pending(store).length, 1); assert.equal(net.writes.length, 0);
    await api.flushWatchlistChanges('https://example.invalid', 'synthetic', { storage: store, fetcher: net.fetcher, locks });
    assert.equal(net.writes[0].changes[0].item.symbol, 'BTC');
    assert.equal('memo' in net.writes[0].changes[0].item, false);
  }
  {
    const { api, store } = setup();
    const key = api.stageRegistrationChanges([], [a, b], new Set(['JP:1234']));
    const batch = JSON.parse(store.getItem(key));
    assert.equal(batch.changes.length, 1);
    assert.equal(batch.changes[0].item.symbol, 'TEST', 'restored registrations are not uploaded along with another live edit');
  }
  console.log('登録銘柄の自動保存: 初期表示・復元・通信中編集・再起動・競合・認証・容量不足・暗号資産/投信保全 PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
