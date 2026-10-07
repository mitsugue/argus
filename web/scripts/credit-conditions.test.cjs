const fs=require('node:fs'),ts=require('typescript'),vm=require('node:vm'),assert=require('node:assert/strict');
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
let current={document:null,readFailed:false,denied:false};
const context={exports:{},URL,require:name=>name.includes('useCreditConditions')?{useCreditConditions:()=>current}:name.endsWith('.css')?{}:require(name)};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/today/CreditConditionsDetails.tsx','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,context);
const doc={schemaVersion:'credit-conditions-v1',snapshotId:'a'.repeat(64),actionAuthority:false,showToday:true,
 dimensions:{borrowingCost:{status:'OBSERVED',direction:'RISING',value:1.5,unit:'PERCENT',dataAsOf:'2026-08-31'},creditQuality:{status:'INSUFFICIENT_DATA'}},
 evidence:[{observationId:'b'.repeat(64),title:'貸出金利',value:1.5,unit:'PERCENT',dataAsOf:'2026-08-31',publicationDate:null,publicationAt:null,
 retrievedAt:'2026-10-08T01:00:00Z',validationStatus:'VERIFIED',revision:0,tablePageFigureRef:'公式系列の参照',sourceUrl:'https://www.boj.or.jp/',publisher:'日本銀行'}],
 sourceHealth:[{sourceId:'boj_credit_cost',publisher:'日本銀行',status:'STALE',cadence:'MONTHLY',count:2},{sourceId:'joint_data_platform',publisher:'金融庁・日本銀行',status:'NOT_ACQUIRED'}]};
const render=creditConditions=>renderToStaticMarkup(React.createElement(context.exports.CreditConditionsDetails,{brief:{creditConditions}}));
const html=render(doc);
for(const text of ['信用環境：','貸出金利は上昇','比較できる数値が不足','古い値・更新待ち','公表時刻 未確認','受領 2026/10/8','全体の分類は未検証','毎日の売買タイミング','予測の入力・成績は変更していません']) assert.ok(html.includes(text),text);
assert.ok(!render({...doc,showToday:false}).includes('信用環境：'),'unchanged data remains in the evidence drawer');
assert.equal(render({...doc,actionAuthority:true}),'');assert.equal(render(undefined),'');
assert.ok(!render({...doc,evidence:[{...doc.evidence[0],sourceUrl:'javascript:alert(1)'}]}).includes('javascript:'));
assert.ok(!fs.readFileSync('src/components/today/CreditConditionsDetails.tsx','utf8').includes('fetch('));
console.log('信用環境：不足・古さ・出典・条件付き表示・外部取得なし PASS');

assert.ok(render({...doc,collectionStatus:'FAILED',showToday:false}).includes('信用環境の更新に失敗しました。受領済みの保存値を表示しています。'));
current={document:doc,readFailed:false,denied:false};
assert.ok(render(undefined).includes('貸出金利は上昇'),'official observations appear without an AI edition');
assert.ok(render({...doc,dimensions:{}}).includes('貸出金利は上昇'),'fresh official projection does not await the old AI edition');
current={document:doc,readFailed:true,denied:false};
assert.ok(render(undefined).includes('最新の保存値を確認できません'));
current={document:null,readFailed:true,denied:true};assert.equal(render(doc),'','authentication denial cannot retain protected observations');

(async()=>{
 const shared={exports:{}};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/sharedPollingStore.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,shared);
 let now=1_000_000,reads=0,timer,answer={status:200,ok:true,json:async()=>doc};
 const visible={visibilityState:'visible'};
 const hooks={exports:{},Date:{now:()=>now},Set,AbortController,document:visible,
  window:{setTimeout:()=>1,clearTimeout:()=>{}},
  fetch:async()=>{reads++;return answer;},
  require:name=>name==='react'?{}:name.includes('sharedPollingStore')?shared.exports:{scheduleVisibleInterval:fn=>{timer=fn;return()=>{};},subscribeInitialVisibleRead:()=>()=>{}}};
 const source=fs.readFileSync('src/hooks/useCreditConditions.ts','utf8').replace('import.meta.env.VITE_ARGUS_BACKEND_URL',"'https://argus.example'");
 vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,hooks);
 const store=hooks.exports.creditConditionsStore,flush=()=>new Promise(resolve=>setImmediate(resolve));
 const stop1=store.subscribe(()=>{}),stop2=store.subscribe(()=>{});await flush();
 assert.equal(reads,1,'multiple displays share one read');assert.equal(store.getSnapshot().document.snapshotId,doc.snapshotId);
 stop1();stop2();const stop3=store.subscribe(()=>{});await flush();assert.equal(reads,1,'navigation within cadence reuses memory');
 now+=300_001;answer={status:500,ok:false};timer();await flush();assert.equal(reads,2);assert.equal(store.getSnapshot().readFailed,true);assert.equal(store.getSnapshot().document.snapshotId,doc.snapshotId,'failed refresh retains exact original edition');
 visible.visibilityState='hidden';now+=60_001;timer();await flush();assert.equal(reads,2,'background does not poll');
 visible.visibilityState='visible';answer={status:403,ok:false};timer();await flush();assert.equal(store.getSnapshot().document,null);assert.equal(store.getSnapshot().denied,true);
 assert.equal(hooks.exports.validCreditConditions({...doc,evidence:[null]}),false);assert.equal(hooks.exports.validCreditConditions({...doc,actionAuthority:true}),false);
 stop3();console.log('信用環境：AI待機から独立・共有保存値・ページ移動の再読取なし・失敗保持・認証拒否 PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
