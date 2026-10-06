'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const crypto = require('node:crypto').webcrypto;
const source = fs.readFileSync('src/lib/accountWatchlistSync.ts', 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const clone = x => JSON.parse(JSON.stringify(x));
class Store {
  constructor() { this.data = new Map(); this.fail = false; this.failKey = ''; }
  get length() { return this.data.size; }
  key(i) { return [...this.data.keys()][i] ?? null; }
  getItem(k) { return this.data.get(k) ?? null; }
  setItem(k, v) { if (this.fail || this.failKey === k) throw Error('quota'); this.data.set(k, v); }
  removeItem(k) { this.data.delete(k); }
}
const item = (id, extra = {}) => ({ id, symbol: id.split('-')[1], market: 'JP', assetType: 'jp_equity',
  source: 'jquants', displayName: '合成銘柄', enabled: true, sortOrder: 0, createdAt: 1, updatedAt: 2, ...extra });
const assetsKey = 'argus.assets.v1';
const joinedKey = 'argus.account-watchlist-joined.v1';
const queue = store => [...store.data.keys()].filter(k => k.startsWith('argus.account-watchlist-pending.v1.'));
function device(assets = [], store = new Store()) {
  const exports = {}, messages = [], events = [];
  let signedIn = true;
  const window = { dispatchEvent: e => events.push(e.type), addEventListener() {}, removeEventListener() {} };
  if (!store.getItem(assetsKey)) store.setItem(assetsKey, JSON.stringify(assets));
  vm.runInNewContext(code, { exports, require: name => name.endsWith('ownerSession')
    ? { hasOwnerSession: () => signedIn, OWNER_AUTH_REQUIRED: true }
    : { setWatchlistSyncState: s => messages.push(s) },
    localStorage: store, crypto, Date, Event, AbortController, setTimeout, clearTimeout, window,
    document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} }, navigator: { onLine: true } });
  return { api: exports, store, messages, events, logout: () => { signedIn = false; } };
}
function server() {
  let state = { revision: 0, initialized: false, assets: [], deleted: [] };
  const receipts = new Map(), calls = [];
  let fail = false, loseAck = false, conflict = null, duringRead = null, malformed = false;
  const response = (value, status = 200) => ({ status, ok: status >= 200 && status < 300, json: async () => clone(value) });
  const fetcher = async (url, init) => {
    assert.ok(url.endsWith('/api/argus/owner-auth/watchlist'));
    calls.push({ method: init.method, body: init.body && JSON.parse(init.body) });
    if (fail) throw Error('offline');
    if (init.method === 'GET') {
      if (duringRead) { const run = duringRead; duringRead = null; run(); }
      return response(malformed ? { assets: [] } : state);
    }
    const body = JSON.parse(init.body);
    const digest = JSON.stringify(body.operations);
    if (receipts.has(body.batchId)) {
      assert.equal(receipts.get(body.batchId), digest);
      return response({ ...state, batchId: body.batchId });
    }
    if (conflict) { const run = conflict; conflict = null; run(); }
    if (body.revision !== state.revision) return response({}, 409);
    const byId = new Map(state.assets.map(a => [a.id, a]));
    const deleted = new Set(state.deleted);
    for (const op of body.operations) {
      if (op.kind === 'remove') { byId.delete(op.id); deleted.add(op.id); }
      if (op.kind === 'add') { byId.set(op.asset.id, op.asset); deleted.delete(op.asset.id); }
      if (op.kind === 'import' && !deleted.has(op.asset.id)) byId.set(op.asset.id, { ...op.asset, ...byId.get(op.asset.id) });
      if (op.kind === 'update' && byId.has(op.id)) {
        const next = { ...byId.get(op.id), ...op.set };
        op.unset.forEach(k => delete next[k]); byId.set(op.id, next);
      }
    }
    state = { revision: state.revision + 1, initialized: true, assets: [...byId.values()].sort((a, b) => a.sortOrder - b.sortOrder || a.id.localeCompare(b.id)), deleted: [...deleted] };
    receipts.set(body.batchId, digest);
    if (loseAck) { loseAck = false; throw Error('connection_lost_after_save'); }
    return response({ ...state, batchId: body.batchId });
  };
  return { fetcher, calls, get state() { return clone(state); },
    set fail(v) { fail = v; }, set loseAck(v) { loseAck = v; }, set malformed(v) { malformed = v; },
    set duringRead(v) { duringRead = v; }, set conflict(v) { conflict = v; },
    mutate(fn) { state = fn(clone(state)); } };
}
function local(d) { return JSON.parse(d.store.getItem(assetsKey)); }
function edit(d, next) {
  const key = d.api.stageAccountRegistrations(local(d), next);
  d.store.setItem(assetsKey, JSON.stringify(next)); d.api.commitAccountRegistrations(key); return key;
}
const sync = (d, s) => d.api.syncAccountRegistrations('https://example.invalid', s.fetcher);
(async () => {
  {
    const s = server(), a = device([item('jp-1234', { memo: '保全', quantity: 9, avgCost: 20 })]);
    await sync(a, s);
    const fresh = device([item('jp-factory', { createdAt: 0, updatedAt: 0 })]);
    await sync(fresh, s);
    assert.deepEqual(local(fresh), local(a), 'normal login automatically loads complete registrations');
    assert.equal(s.state.assets.length, 1, 'factory defaults do not overwrite or pollute shared state');
    edit(fresh, [item('jp-5678', { sortOrder: -1 }), ...local(fresh)]);
    await sync(fresh, s); await sync(a, s);
    assert.deepEqual(local(a), local(fresh), 'add and order propagate');
    assert.equal(local(a)[1].quantity, 9); assert.equal(local(a)[1].memo, '保全');
    const writes = s.calls.filter(c => c.method === 'POST').length;
    await sync(a, s); await sync(fresh, s);
    assert.equal(s.calls.filter(c => c.method === 'POST').length, writes, 'unchanged views never create new writes');
    assert.equal(JSON.stringify(s.calls).includes('ownerToken'), false, 'no separate owner-sync credential');
  }
  {
    const s = server(), a = device([item('jp-1234')]); await sync(a, s);
    const b = device(); await sync(b, s);
    edit(a, [{ ...local(a)[0], memo: '別端末のメモ', updatedAt: 3 }]); await sync(a, s);
    edit(b, [{ ...local(b)[0], sortOrder: -5, updatedAt: 4 }]);
    s.conflict = () => s.mutate(st => ({ ...st, revision: st.revision + 1, assets: [...st.assets, item('jp-9999')] }));
    await sync(b, s);
    assert.equal(local(b).find(x => x.id === 'jp-1234').memo, '別端末のメモ');
    assert.equal(local(b).find(x => x.id === 'jp-1234').sortOrder, -5);
    assert.ok(local(b).some(x => x.id === 'jp-9999'), 'concurrent registration survives revision retry');
  }
  {
    const s = server(), a = device([item('jp-1234')]); await sync(a, s);
    edit(a, [item('jp-1234', { memo: '通信断の編集' })]); s.loseAck = true;
    await assert.rejects(sync(a, s));
    assert.equal(queue(a.store).length, 1, 'ack loss keeps durable batch');
    const id = JSON.parse(a.store.getItem(queue(a.store)[0])).batchId;
    s.mutate(st => ({ ...st, revision: st.revision + 1, assets: st.assets.map(x => ({ ...x, memo: '後続の編集' })) }));
    const restarted = device([], a.store); await sync(restarted, s);
    assert.equal(local(restarted)[0].memo, '後続の編集', 'retry receipt never repeats an old write');
    assert.ok(s.calls.filter(c => c.body?.batchId === id).length === 2);
  }
  {
    const s = server(), a = device([item('jp-1234')]); await sync(a, s);
    const stale = device([item('jp-1234', { memo: '古い端末' })]);
    edit(a, []); await sync(a, s); await sync(stale, s);
    assert.deepEqual(local(stale), [], 'old installation never resurrects a deletion');
    const factory = device([item('jp-factory', { updatedAt: 0 })]); await sync(factory, s);
    assert.deepEqual(local(factory), [], 'deliberately empty account stays empty');
  }
  {
    const s = server(), a = device([]); await sync(a, s);
    assert.equal(s.state.initialized, true, 'empty first account is initialized explicitly');
    edit(a, [item('jp-1234')]); s.fail = true;
    await assert.rejects(sync(a, s)); assert.equal(local(a).length, 1); assert.equal(queue(a.store).length, 1);
    s.fail = false; await sync(a, s); assert.equal(queue(a.store).length, 0);
    s.malformed = true; const before = a.store.getItem(assetsKey);
    await assert.rejects(sync(a, s)); assert.equal(a.store.getItem(assetsKey), before, 'invalid server response never wipes local records');
  }
  {
    const s = server(), a = device([item('jp-1234')]); await sync(a, s);
    const next = [item('jp-1234'), item('jp-5678')];
    const key = a.api.stageAccountRegistrations(local(a), next);
    a.store.setItem(assetsKey, JSON.stringify(next)); // crash before committed bit
    await sync(device([], a.store), s); assert.equal(queue(a.store).length, 0); assert.equal(s.state.assets.length, 2);
    const stopped = device([], a.store);
    const staged = stopped.api.stageAccountRegistrations(local(stopped), []); // crash before local write
    await sync(stopped, s); assert.equal(stopped.store.getItem(staged), null); assert.equal(s.state.assets.length, 2);
    assert.ok(key);
  }
  {
    const s = server(), a = device([item('jp-1234')]); await sync(a, s);
    s.duringRead = () => edit(a, [...local(a), item('jp-5678')]);
    await sync(a, s); assert.equal(s.state.assets.length, 2, 'edit during pull is journaled and retained');
    // Existing explicit backup restoration remains compatible with automatic save.
    a.store.setItem(assetsKey, JSON.stringify([...local(a), item('jp-9999')]));
    await sync(a, s); assert.equal(s.state.assets.length, 3);
    a.logout(); const before = s.calls.length;
    await assert.rejects(sync(a, s)); assert.equal(s.calls.length, before, 'logout never reads or writes private registrations');
  }
  {
    const s = server(), a = device([item('jp-1234')]); await sync(a, s);
    const b = device(); await sync(b, s);
    edit(b, [...local(b), item('jp-5678')]); await sync(b, s);
    a.store.failKey = 'argus.account-watchlist-baseline.v1';
    await assert.rejects(sync(a, s), /quota/);
    assert.equal(local(a).length, 2, 'remote application reached local asset storage');
    a.store.failKey = '';
    const posts = s.calls.filter(c => c.method === 'POST').length;
    await sync(device([], a.store), s);
    assert.equal(s.calls.filter(c => c.method === 'POST').length, posts,
      'crash between remote application and baseline save must never re-upload remote edits');
    assert.equal(local(a).length, 2);
  }
  {
    const s = server(), a = device([item('jp-1234', { memo: '保存済み' })]); await sync(a, s);
    const before = a.store.getItem(assetsKey);
    s.mutate(st => ({ ...st, initialized: false, revision: 0, assets: [], deleted: [] }));
    await assert.rejects(sync(a, s), /server_state_reset/);
    assert.equal(a.store.getItem(assetsKey), before, 'lost server storage must not clear an already joined device');
    edit(a, [...local(a), item('jp-5678')]);
    await assert.rejects(sync(device([], a.store), s), /server_state_reset/);
    assert.equal(queue(a.store).length, 1, 'pending edits survive account storage reset');
  }
  console.log('ログイン共有・並び順・同時編集・通信断・再起動・削除・復元の検査に合格');
})().catch(e => { console.error(e); process.exitCode = 1; });
