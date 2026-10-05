'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const root = path.join(__dirname, '..');
function load(file, deps, extra = {}) {
  const exports = {};
  const src = fs.readFileSync(path.join(root, file), 'utf8').replaceAll('import.meta.env.VITE_ARGUS_BACKEND_URL', "'https://example.invalid'");
  const code = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
  vm.runInNewContext(code, { exports, require: name => deps(name), console, Date, setTimeout, AbortSignal, ...extra });
  return exports;
}
const helper = load('src/lib/watchlistMembershipRestore.ts', () => { throw Error('unexpected import'); });
const local = [
  { id: 'jp-7203', market: 'JP', symbol: '7203', enabled: false, sortOrder: 7, memo: 'keep', quantity: 42, avgCost: 999, extra: { archive: true } },
  { id: 'core-fund', market: 'CORE', symbol: 'FUND-A', enabled: true, sortOrder: 8, monthlyContribution: 5000 },
];
const raw = JSON.stringify(local);
const members = [{ market: 'JP', symbol: '7203', enabled: true }, { market: 'US', symbol: 'TEST', enabled: false, quantity: 777 }, { market: 'US', symbol: 'test' }];
const result = helper.mergeWatchlistMembership(local, members, 123);
assert.equal(result.added, 1);
assert.equal(JSON.stringify(result.assets.slice(0, 2)), raw, 'all existing records and unknown archived fields survive');
assert.equal(result.assets[2].enabled, false);
assert.equal('quantity' in result.assets[2], false, 'membership cannot import portfolio fields');
assert.equal(JSON.stringify(local), raw, 'inputs remain unchanged');
assert.equal(helper.mergeWatchlistMembership(result.assets, members, 456).added, 0, 'retry is idempotent');
assert.throws(() => helper.mergeWatchlistMembership(local, [{ market: 'OTHER', symbol: 'X' }], 123));
assert.throws(() => helper.mergeWatchlistMembership({}, members, 123));
assert.throws(() => helper.mergeWatchlistMembership(local, Array(201).fill(members[0]), 123));
const collision = helper.mergeWatchlistMembership([{ id: 'us-test', market: 'CORE', symbol: 'OTHER' }], [members[1]], 123);
assert.equal(new Set(collision.assets.map(x => x.id)).size, 2, 'existing IDs never collide');

async function restore({ status = 200, corrupt = false, rejectWrite = false } = {}) {
  const store = new Map([['argus.assets.v1', raw], ['argus.ownerSyncToken.v1', 'test-only-token']]);
  const results = []; const events = []; let edits = 0; let release; let writes = 0;
  const React = { createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
    useState: init => [typeof init === 'function' ? init() : init, value => results.push(value)] };
  const card = load('src/components/guide/Layer2BSyncCard.tsx', name => {
    if (name === 'react') return React;
    if (name.endsWith('watchlistMembershipRestore')) return helper;
    if (name.endsWith('/vault')) return { markLocalEdit: () => edits++ };
    if (name.endsWith('TriangleStepLoader')) return { TriangleStepLoader: () => null };
    throw Error(name);
  }, { localStorage: { getItem: key => store.get(key) ?? null, setItem: (key, value) => { if (rejectWrite) throw Error('quota'); writes++; store.set(key, value); } },
    confirm: () => true, Event: class { constructor(type) { this.type = type; } },
    window: { dispatchEvent: e => events.push(e.type) },
    fetch: () => new Promise(resolve => { release = () => resolve({ ok: status === 200, status,
      json: async () => ({ status: 'ok', membership: { members } }) }); }) });
  const tree = card.Layer2BSyncCard({ assets: local });
  const find = node => node && typeof node === 'object' && (node.type === 'button' && node.children.includes('銘柄を復元') ? node : node.children?.map(find).find(Boolean));
  const pending = find(tree).props.onClick();
  const changed = [...local, { id: 'jp-new', market: 'JP', symbol: '9999', memo: 'edited-during-request' }];
  const before = corrupt ? 'broken-json' : JSON.stringify(changed);
  store.set('argus.assets.v1', before);
  release(); await pending;
  if (status !== 200 || corrupt || rejectWrite) {
    assert.equal(store.get('argus.assets.v1'), before, 'failure does not replace original storage');
    assert.equal(edits, 0); assert.equal(events.length, 0);
  } else {
    const saved = JSON.parse(store.get('argus.assets.v1'));
    assert.equal(JSON.stringify(saved.slice(0, 3)), before, 'edits during network request survive');
    assert.equal(saved.length, 4); assert.equal(writes, 1); assert.equal(edits, 1);
    assert.equal(events.join(), 'argus:data-synced');
  }
}
(async () => {
  await restore(); await restore({ status: 401 }); await restore({ corrupt: true }); await restore({ rejectWrite: true });
  console.log('銘柄復元: 元記録・通信中の変更・重複・異常応答・容量不足の保全 PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
