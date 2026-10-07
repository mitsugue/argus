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
const { AssetOutlookSummary } = require('../src/components/assetDesk/AssetOutlookSummary.tsx');
const target = { market:'JP', symbol:'1001', mean:1200, analysts:8, currency:'JPY', fetchedAt:'2026-10-06T03:00:00Z', source:'Yahoo Finance', gapPct:99, priceAtFetch:500 };
assert.equal(domain.validAnalystTarget(target, 'JP:1001'), true);
for (const patch of [{ mean:NaN }, { analysts:-2 }, { analysts:1.2 }, { fetchedAt:'bad' }, { currency:'USD' }]) assert.equal(domain.validAnalystTarget({...target, ...patch}, 'JP:1001'), false);
assert.equal(domain.validAnalystTarget(target, 'US:1001'), false);
assert.equal(domain.analystTargetGap(target, 1000).toFixed(1), '20.0');
assert.equal(domain.analystTargetGap(target, null), null);
const supply = {market:'JP', supplyDemandRank:'C', conditionJa:'改善中だが信用買い残はまだ重い', directness:'direct_data', supplyDemandLevel:'very_heavy', levelJa:'かなり重い', sourceDates:{weeklyMargin:'2026-10-02',jsfDaily:'2026/10/06'}};
const render = patch => renderToStaticMarkup(React.createElement(AssetOutlookSummary, {market:'JP', target, currentPrice:1000, loading:false, refreshFailed:false, supply, ...patch}));
const html = render({});
for (const fact of ['1,200円','現在値比 +20.0%','8人','10/6取得','信用 10/2','日証金 10/6','かなり重い']) assert.ok(html.includes(fact), fact);
assert.ok(!html.includes('99.0%'));
assert.ok(render({refreshFailed:true}).includes('更新未確認・保存値'));
assert.ok(render({target:undefined,targetStatus:'NO_TARGET'}).includes('取得元に目標値なし'));
assert.ok(render({target:undefined,refreshFailed:true}).includes('取得未確認'));
assert.ok(!render({currentPrice:null}).includes('現在値比'));
assert.ok(render({supply:{...supply, directness:'stale_context', supplyDemandRank:'D'}}).includes('保存評価 D'));
assert.ok(render({supply:{...supply, market:'US'}}).includes('判定保留'));
assert.equal(render({market:'CRYPTO'}), '');
const summary = fs.readFileSync('src/components/assetDesk/AssetDecisionSummary.tsx', 'utf8');
assert.ok(summary.includes('<AssetOutlookSummary') && !summary.includes('gapPct.toFixed'));
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
const usHtml = render({market:'US', target:usTarget, currentPrice:120,
  supply:{...supply, market:'US', supplyDemandRank:'B', conditionJa:'大口買い越し'}});
for (const fact of ['$150', '現在値比 +25.0%', '大口買い越し', '実測大口フロー']) assert.ok(usHtml.includes(fact), fact);
for (const fact of ['買い残', 'かなり重い', '日証金']) assert.ok(!usHtml.includes(fact), fact);
assert.ok(render({market:'US', target:undefined, supply:undefined}).includes('実測フロー未取得'));
const {fmtPrice} = require('../src/components/assetDesk/deskFormat.ts');
assert.equal(fmtPrice('US', 1234.5), '$1,234.50');
assert.equal(fmtPrice('US', Infinity), '—');
console.log('US first-card target, price format and evidence isolation PASS');
