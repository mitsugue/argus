'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const root = path.join(__dirname, '..');
function compile(file) {
  return ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: file,
  }).outputText;
}
function moduleAt(file, requireStub, extra = {}) {
  const exports = {};
  vm.runInNewContext(compile(file), { exports, require: requireStub, console, ...extra }, { filename: file });
  return exports;
}
const { watchlistProjection } = moduleAt('src/domain/watchlistProjection.ts', () => { throw Error('unexpected dependency'); });
const archived = [{ id: 'jp-7203', symbol: '7203', displayName: 'Toyota', market: 'JP',
  assetType: 'jp_equity', source: 'jquants', enabled: true, sortOrder: 0, createdAt: 123, updatedAt: 456,
  quantity: 150, avgCost: 2345, monthlyContribution: 12000, targetAllocation: 0.2, currentAllocation: 0.3,
  purchaseReason: 'original reason', holdingPeriod: 'original horizon', memo: 'retained note',
  futurePrivateExtension: { cash: 9876 } }];
const original = JSON.stringify(archived);
const records = new Map([['argus.assets.v1', original]]);
const localStorage = { getItem: key => records.get(key) ?? null, setItem: (key, value) => records.set(key, value) };
const slots = []; let slot = 0; let effects = []; const listeners = new Map(); let edits = 0;
const React = {
  createContext: () => ({}), createElement: (_, props) => props.value, useContext: () => null,
  useState: init => { const index = slot++; if (!(index in slots)) slots[index] = typeof init === 'function' ? init() : init;
    return [slots[index], next => { slots[index] = typeof next === 'function' ? next(slots[index]) : next; }]; },
  useRef: init => { const index = slot++; return slots[index] ?? (slots[index] = { current: init }); },
  useMemo: fn => fn(), useCallback: fn => fn,
  useEffect: (fn, deps) => { const index = slot++; const previous = slots[index]; slots[index] = deps;
    if (!previous || deps.some((x, i) => x !== previous[i])) effects.push(fn); },
};
const hook = moduleAt('src/hooks/useAssets.ts', name => {
  if (name === 'react') return React;
  if (name.endsWith('/watchlistProjection')) return { watchlistProjection };
  if (name.endsWith('/vault')) return { markLocalEdit: () => edits++ };
  if (name.endsWith('/assetMerge')) return { recordTombstone: () => {} };
  throw Error(`unexpected hook dependency ${name}`);
}, { localStorage, window: { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: () => {} } });
function render() { slot = 0; effects = []; const value = hook.AssetsProvider({ children: null }); effects.forEach(fn => fn()); return value; }
let api = render();
assert.equal(records.get('argus.assets.v1'), original, 'mount must preserve every raw archived field byte for byte');
assert.equal(edits, 0, 'upgrade must not stamp a new owner edit');
for (const key of ['quantity', 'avgCost', 'monthlyContribution', 'targetAllocation', 'currentAllocation',
  'purchaseReason', 'holdingPeriod', 'futurePrivateExtension']) assert.equal(key in api.assets[0], false, key);
assert.equal(api.assets[0].memo, 'retained note');
assert.equal(JSON.stringify(api.archivedAssets), original, 'recovery receives the unmodified archive');
api.toggle('jp-7203'); api = render();
const changed = JSON.parse(records.get('argus.assets.v1'))[0];
assert.equal(changed.enabled, false);
assert.equal(changed.quantity, 150); assert.equal(changed.avgCost, 2345);
assert.deepEqual(changed.futurePrivateExtension, { cash: 9876 });
assert.equal(edits, 1);
const restored = JSON.parse(original); restored[0].quantity = 250;
localStorage.setItem('argus.assets.v1', JSON.stringify(restored));
listeners.get('argus:data-synced')(); api = render();
assert.equal(api.archivedAssets[0].quantity, 250, 'existing backup restore keeps original quantities');
assert.equal('quantity' in api.assets[0], false, 'restored archives must not reactivate portfolio analysis');
assert.equal(edits, 1, 'restoration is not a new owner edit');

// Actual notification execution: a registered symbol with no quantity receives
// worsening-condition notices once, through the existing throttle and dedupe.
let time = Date.parse('2026-09-17T01:00:00Z');
class Clock extends Date { constructor(...args) { super(...(args.length ? args : [time])); } static now() { return time; } }
const notices = moduleAt('src/lib/notifications.ts', () => ({ jpDisplay: (s, n) => n || s }), { Date: Clock, localStorage, window: {} });
const input = { apItems: [], eventNames: [], sdBySymbol: {}, flowBySymbol: {},
  scenarioBySymbol: { '7203': { dominant: 'bullish', isHeld: false, name: 'Toyota' } },
  hasHoldings: false, watchlistOnly: true, snapshotAgeDays: null, vaultConfigured: true,
  localExportAgeDays: 0, restoreVerified: true, ownerSnapshotCurrent: true };
notices.runNotificationEngine(input); time += 61000;
input.scenarioBySymbol['7203'].dominant = 'bearish';
assert.equal(notices.runNotificationEngine(input).delivered, 1);
time += 61000;
assert.equal(notices.runNotificationEngine(input).delivered, 0, 'unchanged warning is not sent again');
const saved = JSON.parse(records.get('argus.notifications.v1'));
assert.equal(saved.items[0].eventType, 'scenario_change');
assert.equal(saved.items[0].symbol, '7203');

time += 61000;
input.apItems = [{ symbol: '7203', assetName: 'Toyota', priorityRank: 'P1', isHeld: false,
  category: 'flow_watch', whyJa: 'verified flow change', checkNextJa: 'next session' }];
assert.equal(notices.runNotificationEngine(input).delivered, 1, 'P1 watchlist warning does not need a holding');
time += 61000;
assert.equal(notices.runNotificationEngine(input).delivered, 0);

const intel = fs.readFileSync(path.join(root, 'src/hooks/useAssetIntel.ts'), 'utf8');
for (const retired of ['buildPositionExposure(', 'buildLocalFireCore(', 'buildStrategy(', 'publishFireCore(', 'publishStrategy('])
  assert.equal(intel.includes(retired), false, `retired calculator remains disconnected: ${retired}`);
const today = fs.readFileSync(path.join(root, 'src/routes/CommandCenter.tsx'), 'utf8');
assert.equal(today.includes('maybeDailySnapshot('), false);
assert.match(intel, /appendDeviceLocalSdaLedger\(result, adapter\)/, 'formal market judgment history stays active');
console.log('watchlist retirement: archive preservation, restore isolation, quantity-free notifications, dedupe and execution boundary PASS');
