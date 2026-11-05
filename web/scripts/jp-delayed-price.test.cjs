'use strict';
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const assert = require('node:assert/strict'), ts = require('typescript');
const compile = (source,file) => ts.transpileModule(source, {fileName:file,compilerOptions:{module:ts.ModuleKind.CommonJS,
 target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
for (const ext of ['.ts','.tsx']) require.extensions[ext]=(m,f)=>m._compile(compile(fs.readFileSync(f,'utf8'),f),f);
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const d=require('../src/domain/jpDelayedPrice.ts');
const now=Date.parse('2026-11-05T01:00:00Z');
const row={symbol:'1001',provider:'YAHOO_DELAYED',price:123.5,changePct:2.9,
 sourceTimestamp:'2026-11-05T00:40:00Z',receivedAt:'2026-11-05T00:59:59Z',delaySeconds:1199,
 realtime:false,actionAuthority:false,lastError:null};
const doc={schemaVersion:'argus-jp-delayed-display-v1',provider:'YAHOO_DELAYED',actionAuthority:false,
 readAt:'2026-11-05T01:00:00Z',requestedSymbols:['1001'],symbols:{1001:row}};
assert.equal(d.jpDelayedPrice(doc,'1001',now).price,123.5);
assert.equal(d.jpDelayedPrice(doc,'1001',now).current,true);
for (const patch of [{price:NaN},{price:0},{price:true},{sourceTimestamp:'2026-11-04T00:40:00Z'},
 {receivedAt:'2026-11-05T01:00:01Z'},{sourceTimestamp:'2026-11-05T01:00:01Z'},
 {sourceTimestamp:'2026-11-05T09:40:00'},{delaySeconds:-1},{delaySeconds:0},{provider:'OTHER'},
 {symbol:'1002'},{realtime:true},{actionAuthority:true}]) {
 assert.equal(d.jpDelayedPrice({...doc,symbols:{1001:{...row,...patch}}},'1001',now),null,JSON.stringify(patch));
}
assert.equal(d.jpDelayedPrice(doc,'1002',now),null);
assert.equal(d.jpDelayedPrice({...doc,actionAuthority:true},'1001',now),null);
assert.equal(d.jpDelayedPrice(doc,'1001',now+181000).current,false,'receipt expiry independent of trade delay');
assert.equal(d.jpDelayedPrice({...doc,symbols:{1001:{...row,lastError:'HTTP_503'}}},'1001',now).current,false);
assert.equal(d.jpDelayedPrice(doc,'1001',now+86400000),null,'prior day does not become today');

// Render the actual card with current/old broker evidence: fresh broker wins,
// delayed backup beats only old references, and the analytic object is unchanged.
let broker=null, backup=doc;
const file=path.resolve(__dirname,'../src/components/assetDesk/AssetDecisionSummary.tsx');
const m=new Module(file,module);m.filename=file;m.paths=module.paths;
const orig=m.require.bind(m);
m.require=name=>name.endsWith('/useDecisionEvidence')?{useTachibanaLiveDocument:()=>broker}
 :name.endsWith('/jpDelayedPrice')?{...d,useJpDelayedPriceDocument:()=>backup}
 :name.endsWith('/useAnalystTargets')?{useAnalystTargetState:()=>({items:{},availability:{},loading:false})}
 :name.endsWith('/AssetEarnings')?{AssetEarningsDate:()=>null}
 :name.endsWith('/AssetOutlookSummary')?{AssetOutlookSummary:()=>null}:orig(name);
m._compile(compile(fs.readFileSync(file,'utf8'),file),file);
const card={asset:{market:'JP',symbol:'1001'},genre:'jp',strat:{status:'delayed',price:100},
 decisionFirst:{symbol:'1001',name:'確認銘柄',priceText:'100円',changePct:-2,dataStatus:'前日'}};
const before=JSON.stringify(card), originalNow=Date.now;Date.now=()=>now;
try {
 const render=()=>renderToStaticMarkup(React.createElement(m.exports.AssetDecisionSummary,{d:card,open:false,onToggle(){}}));
 let html=render();
 for (const text of ['123.5円','遅延','価格 09:40','受信 09:59','20分前','Yahoo']) assert.ok(html.includes(text),text);
 broker={provider:'TACHIBANA',enabled:true,displayApproved:true,mode:'DISPLAY',shadowOnly:true,authoritative:false,
 status:'LIVE',symbols:{1001:{provider:'TACHIBANA',price:130,changePct:8.3,freshness:'FRESH',
 sourceTimestamp:'2026-11-05T00:59:59Z',receivedAt:'2026-11-05T00:59:59Z',sourceTimestampPrecision:'SECOND',marketStatus:'OPEN',realtimeClassification:'CURRENT_MARKET_SNAPSHOT'}}};
 html=render();assert.ok(html.includes('130円')&&html.includes('リアルタイム')&&!html.includes('Yahoo'));
 broker={...broker,status:'STALE',symbols:{1001:{...broker.symbols[1001],freshness:'STALE',
 sourceTimestamp:'2026-11-05T00:30:00Z',receivedAt:'2026-11-05T00:30:00Z'}}};
 html=render();assert.ok(html.includes('123.5円')&&html.includes('Yahoo'),'delayed beats stale broker');
 broker=null;backup={...doc,symbols:{1001:{...row,lastError:'HTTP_429'}}};
 html=render();assert.ok(html.includes('更新失敗・保存価格')&&!html.includes('リアルタイム'));
 assert.equal(JSON.stringify(card),before,'no decision, history, notification or base price mutation');
} finally { Date.now=originalNow; }
console.log('JP delayed admission, source/receipt expiry and actual card source priority PASS');
