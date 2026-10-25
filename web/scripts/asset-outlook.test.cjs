'use strict';
const fs = require('fs');
const ts = require('typescript');
const assert = require('node:assert/strict');
for (const ext of ['.ts', '.tsx']) require.extensions[ext] = (m, file) => m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop:true }
}).outputText, file);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const domain = require('../src/domain/assetOutlook.ts');
const target = { market:'JP', symbol:'1001', mean:1200, analysts:8, currency:'JPY', fetchedAt:'2026-10-06T03:00:00Z', source:'Yahoo Finance', gapPct:99, priceAtFetch:500 };
assert.equal(domain.validAnalystTarget(target, 'JP:1001'), true);
for (const patch of [{ mean:NaN }, { analysts:-2 }, { analysts:1.2 }, { fetchedAt:'bad' }, { currency:'USD' }]) assert.equal(domain.validAnalystTarget({...target, ...patch}, 'JP:1001'), false);
assert.equal(domain.validAnalystTarget(target, 'US:1001'), false);
assert.equal(domain.analystTargetGap(target, 1000).toFixed(1), '20.0');
assert.equal(domain.analystTargetGap(target, null), null);
const supply = {market:'JP', supplyDemandRank:'C', conditionJa:'改善中だが信用買い残はまだ重い', directness:'direct_data', supplyDemandLevel:'very_heavy', levelJa:'かなり重い', sourceDates:{weeklyMargin:'2026-10-02',jsfDaily:'2026/10/06'}};
// 2026-10-25 (owner): the stock page shows four numbers. The target gap uses
// the displayed price, never the provider's price-at-fetch difference.
const numbers = fs.readFileSync('src/components/assetDesk/AssetNumbers.tsx', 'utf8');
for (const used of ['analystTargetGap(target, price)', 'outlookMoney(target.mean, market)', 'supplyDemandRank',
  'ratios?.margin', 'earningsShortDate(earnings)', 'relativeToNikkeiPct']) assert.ok(numbers.includes(used), used);
assert.ok(!numbers.includes('gapPct'));
assert.ok(fs.readFileSync('src/components/assetDesk/AssetDecisionCard.tsx', 'utf8').includes('<AssetNumbers d={d} />'));
const desk = fs.readFileSync('src/components/assetDesk/AssetDeskList.tsx', 'utf8');
assert.ok(desk.includes('sdBySym.get(`${a.market}:${sym}`)'));
console.log('Initial analyst/supply facts, current quote comparison, saved/missing states PASS');

// A different symbol's failed acquisition must not label a successful target as saved.
(async () => {
  const Module = require('module');
  const path = require('path');
  const file = path.resolve('src/hooks/useAnalystTargets.ts');
  const subscriptions = [];
  let interval, calls = 0, failRead = false;
  const originalFetch = global.fetch;
  global.fetch = async () => {
    calls++;
    if (failRead) throw new Error('offline');
    return { ok:true, json:async () => ({actionAuthority:false, lastError:'partial_target_fetch_failed',
      items:{'JP:1001':{...target,acquisitionStatus:'AVAILABLE'}},
      earningsItems:{'JP:1001':{market:'JP',symbol:'1001',source:'Yahoo Finance',fetchedAt:target.fetchedAt,currency:'JPY',actionAuthority:false,
        next:{from:'2026-11-02',to:'2026-11-02',certainty:'PROVIDER_ESTIMATE',timezone:'Asia/Tokyo'},previous:null,estimate:null}},
      availability:{'JP:1001':{status:'AVAILABLE'},'JP:1002':{status:'HTTP_503'}}}) };
  };
  try {
    const m = new Module(file, module); m.filename = file; m.paths = module.paths;
    const nativeRequire = m.require.bind(m);
    m.require = name => name === 'react' ? {useSyncExternalStore: (subscribe, snapshot) => {
      subscriptions.push(subscribe(() => {})); return snapshot();
    }} : name.endsWith('/pollingPolicy') ? {
      scheduleVisibleInterval: fn => {interval = fn; return () => {};},
      subscribeInitialVisibleRead: () => () => {},
    } : nativeRequire(name);
    m._compile(ts.transpileModule(fs.readFileSync(file,'utf8').replaceAll('import.meta.env',
      '({VITE_ARGUS_BACKEND_URL:"https://snapshot.test"})'),{
      compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}
    }).outputText,file);
    const hook = m.exports.useAnalystTargetState;
    hook(); hook();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls,1);
    const current = hook();
    assert.equal(current.items['JP:1001'].mean,1200);
    assert.equal(current.earnings['JP:1001'].next.from,'2026-11-02');
    assert.equal(current.refreshFailed,false);
    assert.equal(current.availability['JP:1002'].status,'HTTP_503');
    failRead = true; interval(); interval();
    await new Promise(resolve => setImmediate(resolve));
    const saved = hook();
    assert.equal(calls,2);
    assert.equal(saved.refreshFailed,true);
    assert.equal(saved.items['JP:1001'].mean,1200);
    assert.equal(saved.earnings['JP:1001'].next.from,'2026-11-02');
    console.log('Shared target read, per-symbol failure isolation and retained snapshot PASS');
  } finally { subscriptions.forEach(stop => stop()); global.fetch = originalFetch; }
})().catch(error => { console.error(error); process.exitCode = 1; });

// US shares first-card facts; JP credit levels cannot masquerade as US evidence.
const usTarget = {...target, market:'US', symbol:'MU', mean:150, currency:'USD'};
assert.equal(domain.outlookMoney(usTarget.mean, 'US'), '$150');
assert.equal(domain.analystTargetGap(usTarget, 120).toFixed(1), '25.0');
assert.ok(numbers.includes("d.sdg?.market === market"), 'JP credit evidence never shows on a US stock');
const {fmtPrice} = require('../src/components/assetDesk/deskFormat.ts');
assert.equal(fmtPrice('US', 1234.5), '$1,234.50');
assert.equal(fmtPrice('US', Infinity), '—');
console.log('US first-card target, price format and evidence isolation PASS');
