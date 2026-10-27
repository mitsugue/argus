'use strict';
const fs = require('fs');
const ts = require('typescript');
const assert = require('node:assert/strict');
const Module = require('module');
for (const ext of ['.ts', '.tsx']) require.extensions[ext] = (m, file) => m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true }
}).outputText, file);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const domain = require('../src/domain/assetEarnings.ts');
const row = {symbol:'TEST',market:'US',source:'Yahoo Finance',fetchedAt:'2026-10-07T10:00:00Z',currency:'USD',actionAuthority:false,
  next:{from:'2026-11-02',to:'2026-11-04',certainty:'PROVIDER_ESTIMATE',timezone:'America/New_York'},
  previous:{currency:'USD',periodEnd:'2026-06-30',epsActual:2,epsEstimate:1.8,surprisePct:11.1},
  estimate:{epsCurrency:'USD',revenueCurrency:'USD',periodEnd:'2026-09-30',eps:2.1,epsLow:1.9,epsHigh:2.4,analysts:8,epsGrowthPct:10,revenue:1000000000,revenueAnalysts:7,revenueGrowthPct:12,eps30DaysAgo:2}};
assert.ok(domain.validAssetEarnings(row,'US:TEST'));
for (const patch of [{actionAuthority:true},{currency:'?'},{next:{...row.next,from:'2026-02-31'}},{previous:{...row.previous,epsActual:Infinity}},
  {estimate:{...row.estimate,analysts:null}},{market:'JP'}]) assert.equal(domain.validAssetEarnings({...row,...patch},'US:TEST'),false);
assert.equal(domain.earningsDateLabel(row,new Date('2026-12-01')), '次回決算 日付未取得');
assert.equal(domain.earningsToday(row,new Date('2026-10-08T00:01:00+09:00')),'2026-10-07');
let state = {earnings:{'US:TEST':row},loading:false,refreshFailed:false};
const file = require('path').resolve('src/components/assetDesk/AssetEarnings.tsx');
const m = new Module(file,module);m.filename=file;m.paths=module.paths;
const native = m.require.bind(m);
m.require = name => name.endsWith('/useAnalystTargets') ? {useAnalystTargetState:()=>state} : native(name);
m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText,file);
const {AssetEarningsDate,AssetEarningsDetails} = m.exports;
const render = () => renderToStaticMarkup(React.createElement(AssetEarningsDetails,{market:'US',symbol:'TEST'}));
const html=render();
for (const text of ['前回の決算','次回の注目点','見通し','2026-06-30期','EPS','8人','7人','上方修正']) assert.ok(html.includes(text),text);
// 2026-10-25 (owner): no caveats or source lines; a missing part is one word.
for (const text of ['発表日は未取得','推測で補いません','更新未確認']) assert.ok(!html.includes(text), text);
assert.ok(!/\d+\/\d+取得/.test(html), 'no source/fetch line');
state={...state,earnings:{'US:TEST':{...row,currency:'JPY',estimate:{...row.estimate,revenueCurrency:'JPY'}}}};
assert.ok(render().includes('$2.00') && render().includes('￥1,000,000,000'));
state={...state,earnings:{'US:TEST':{...row,previous:{...row.previous,currency:undefined},estimate:{...row.estimate,epsCurrency:undefined}}}};
assert.ok(render().includes('通貨未確認') && !render().includes('EPSは$2.00') && !render().includes('30日前の予想'));
state={...state,earnings:{'US:TEST':row}};
const date = renderToStaticMarkup(React.createElement(AssetEarningsDate,{market:'US',row}));
assert.ok(date.includes('11/2〜11/4') && date.includes('米東部'));
assert.equal(renderToStaticMarkup(React.createElement(AssetEarningsDate,{market:'CRYPTO',row})), '');
state={...state,earnings:{}};
assert.equal((render().match(/未取得/g)||[]).length,3);
const summary=fs.readFileSync('src/components/assetDesk/AssetDecisionSummary.tsx','utf8');
const details=fs.readFileSync('src/components/assetDesk/AssetDecisionCard.tsx','utf8');
assert.ok(summary.includes('<AssetEarningsDate'));
assert.ok(details.includes('<AssetEarningsDetails'));
console.log('決算の日付・期末・予想の区別、根拠なし表示、閉じたカードと詳細 PASS');
const official = {...row,market:'JP',symbol:'1001',next:{from:'2026-11-03',to:'2026-11-03',certainty:'COMPANY_SCHEDULE',
  timezone:'Asia/Tokyo',source:'J-Quants 決算発表予定日',publishedDate:'2026-10-07',fetchedAt:row.fetchedAt}};
assert.ok(domain.validAssetEarnings(official,'JP:1001'));
assert.equal(domain.earningsDateLabel(official,new Date('2026-10-08')), '次回決算 11/3（会社予定）');
assert.equal(domain.validAssetEarnings({...official,next:{...official.next,source:'unknown'}},'JP:1001'),false);
assert.equal(domain.validAssetEarnings({...official,market:'US'},'US:1001'),false);
const scheduledHtml = renderToStaticMarkup(React.createElement(AssetEarningsDate,{market:'JP',row:official,refreshFailed:true}));
assert.ok(scheduledHtml.includes('会社予定') && !scheduledHtml.includes('更新未確認'));
assert.ok(renderToStaticMarkup(React.createElement(AssetEarningsDate,{market:'JP',row:{...official,scheduleStatus:'FETCH_FAILED'}})).includes('更新未確認'));
const correctedCompany = {...official,previous:null,estimate:null,company:{disclosedDate:'2026-07-31',periodEnd:'2026-06-30',
  periodType:'1Q',fiscalYearEnd:'2027-03-31',operatingProfit:100000000,forecastOperatingProfit:450000000,consolidated:true,
  source:'J-Quants 決算短信',currency:'JPY',receivedAt:'2026-08-01T00:00:00Z',forecastDisclosedDate:'2026-10-01',forecastReceivedAt:row.fetchedAt}};
assert.ok(domain.validAssetEarnings(correctedCompany,'JP:1001'));
assert.equal(domain.validAssetEarnings({...correctedCompany,company:{...correctedCompany.company,forecastDisclosedDate:'2026-02-31'}},'JP:1001'),false);
state={...state,earnings:{'JP:1001':correctedCompany},refreshFailed:false};
const companyHtml=renderToStaticMarkup(React.createElement(AssetEarningsDetails,{market:'JP',symbol:'1001'}));
for(const text of ['7/31発表','営業利益は1億円','会社予想は営業利益4.5億円','10/1発表'])assert.ok(companyHtml.includes(text),text);
// 2026-10-27 (owner, N-07): the measured move after releases, one line on the stock page.
{
  const reactions={rows:[{disclosedDate:'2026-08-06',disclosedTime:'15:30',timing:'AFTER_CLOSE',session:'2026-08-07',gapPct:6.93,dayPct:8.91,topixPct:1,excessPct:7.91},
    {disclosedDate:'2026-05-08',disclosedTime:'13:00',timing:'INTRADAY',session:'2026-05-08',gapPct:null,dayPct:-2.1,topixPct:null,excessPct:null}],count:2,ups:1};
  assert.ok(domain.validEarningsReactions(reactions));
  assert.equal(domain.validEarningsReactions({...reactions,count:3}),false);
  assert.equal(domain.validEarningsReactions({...reactions,rows:[{...reactions.rows[0],dayPct:NaN}],count:1,ups:1}),false);
  state={...state,earnings:{'JP:1001':{...correctedCompany,reactions}},refreshFailed:false};
  const html=renderToStaticMarkup(React.createElement(AssetEarningsDetails,{market:'JP',symbol:'1001'}));
  assert.ok(html.includes('data-earnings-reactions="2"'),'決算の後の値動きの1行');
  assert.ok(/決算の後の値動き：前回 .*\+8\.9%.*TOPIX比 \+7\.9%.*過去2回で上げ1回/.test(html.replace(/<[^>]+>/g,'')),html);
  state={...state,earnings:{'JP:1001':{...correctedCompany,reactions:{rows:[],count:0,ups:0}}}};
  assert.ok(!renderToStaticMarkup(React.createElement(AssetEarningsDetails,{market:'JP',symbol:'1001'})).includes('決算の後の値動き'));
  console.log('earnings reactions: PASS');
}
