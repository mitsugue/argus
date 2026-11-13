const ts = require('typescript');
const fs = require('node:fs'); const vm = require('node:vm'); const assert = require('node:assert/strict');
const ctx = {exports: {}, Date, Set, URL};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/marketBrief.ts','utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText, ctx);
const valid = ctx.exports.validMarketBrief;
const id = 'brief-fact-'+'a'.repeat(64), old = 'brief-fact-'+'b'.repeat(64);
const fact = {evidenceId:id,text:'実測値を確認',source:'official_sensor',priority:'P0',verification:'VERIFIED'};
const sections = Object.fromEntries(['view','reasons','changes','impact','next','invalidation'].map(key => [key,
 {textJa:'確認した情報です。',evidenceIds:['changes','impact'].includes(key)?[]:[id],kind:['changes','impact'].includes(key)?'UNKNOWN':'INFERENCE'}]));
const doc = {schemaVersion:'argus-market-brief-v1',generatedAt:'2026-09-12T10:00:00Z',sdaAuthority:false,
 now:'要約',why:'理由',next:'確認',chips:{chart:'',news:'',nextEvent:'',mainRisk:''},facts:[fact],aiText:null,
 unifiedStatus:'GENERATED',unifiedContext:{contextId:'c'.repeat(64),facts:[fact],previousFacts:[]},
 unifiedSummary:{schemaVersion:'argus-unified-brief-v1',contextId:'c'.repeat(64),actionAuthority:false,
 ownerContextAvailable:false,historyStatus:'PROCESS_MEMORY_ONLY',sections}};
assert.equal(valid(doc),true);
assert.equal(valid({...doc,unifiedSummary:null,unifiedStatus:'AWAITING_AI'}),true);
for(const patch of [{aiDiagnostics:{returnedModel:{}}},{lastSuccessfulAiAt:{}},{chips:null},{facts:null},{sdaAuthority:true},{generatedAt:'bad'}, {unifiedSummary:null},
 {unifiedContext:{...doc.unifiedContext,facts:[null]}},
 {unifiedSummary:{...doc.unifiedSummary,contextId:'d'.repeat(64)}},
 {unifiedSummary:{...doc.unifiedSummary,sections:{...sections,view:{...sections.view,evidenceIds:[old]}}}},
 {unifiedSummary:{...doc.unifiedSummary,sections:{...sections,impact:{...sections.view}}}},
 {unifiedSummary:{...doc.unifiedSummary,sections:{...sections,view:{...sections.view,kind:'FACT'}}}}]) assert.equal(valid({...doc,...patch}),false);
console.log('Market brief response/authority/reference validation PASS');

const reference = {scope:'published_metadata_snapshot',eventId:'nie-1234567890abcdef',revision:2,
 publishedAt:'2026-09-12T09:00:00Z',receivedAt:'2026-09-12T09:02:00Z',observedAt:null,url:'https://example.org/decision',sourceLabel:'公式発表'};
assert.equal(valid({...doc,facts:[{...fact,provenance:reference}]}),true);
for(const url of ['javascript:alert(1)','https://secret@example.org/path']) assert.equal(valid({...doc,facts:[{...fact,provenance:{...reference,url}}]}),false);

const moreFacts = Array.from({length:64}, (_,i) => ({...fact,evidenceId:'brief-fact-'+i.toString(16).padStart(64,'0')}));
assert.equal(valid({...doc,unifiedStatus:'AWAITING_AI',unifiedSummary:null,facts:moreFacts}),true);
assert.equal(valid({...doc,unifiedStatus:'AWAITING_AI',unifiedSummary:null,facts:[...moreFacts,fact]}),false);
assert.equal(valid({...doc,facts:[{...fact,provenance:{...reference,sourceResponseSha256:'a'.repeat(64)}}]}),true);
assert.equal(valid({...doc,facts:[{...fact,provenance:{...reference,sourceResponseSha256:{}}}]}),false);

assert.equal(valid({...doc, unifiedSummary:{...doc.unifiedSummary,historyStatus:'LOCAL_DURABLE'}}),true);

for (const errorCode of [null, 'credit_balance_exhausted', 'organization_spend_limit_exceeded', 'project_spend_limit_exceeded', 'organization_usage_limit_exceeded', 'insufficient_quota', 'rate_limit_exceeded', 'slow_down']) {
 assert.equal(valid({...doc, aiDiagnostics:{errorCode}}), true);
}
for (const errorCode of [{}, [], 'unreviewed-provider-text']) {
 assert.equal(valid({...doc, aiDiagnostics:{errorCode}}), false);
}

// A valid AI summary must keep the current layout when the separate plan is missing or invalid.
const React=require('react'), {renderToStaticMarkup}=require('react-dom/server');
let shown=doc, recovered=null, requestFailed=false;
const cardContext={exports:{},Date,require(name){
 if(name.endsWith('.css')) return {};
 if(name.includes('/useMarketBrief')) return {useMarketBrief:()=>({brief:shown,error:requestFailed,loading:false,retry:()=>{}})};
 if(name.includes('/presentationIntent')) return {editorialEdition:()=>null,readableBriefEdition:v=>recovered??v};
 if(name.includes('/TodayDecisionStrip')) return {TodayDecisionStrip:()=>React.createElement('section',{'data-four-cards':'visible'})};
 if(name.includes('/MarketPositionCard')) return {MarketPositionCard:()=>null};
 if(name.includes('/marketWording')) return {marketChanges:v=>v,marketWording:v=>v};
 if(name.includes('/screenNotes')) return (()=>{const m={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/screenNotes.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{exports:m.exports,RegExp});return m.exports;})();
 if(name.includes('/NumericalResearchDetails')) return {NumericalResearchDetails:()=>null};
 if(name.includes('/CreditConditionsDetails')) return {CreditConditionsDetails:()=>null};
 if(name.includes('/FiscalEnvironmentDetails')) return {FiscalEnvironmentDetails:()=>null};
 if(name.includes('/MarketAnalysisHistory')) return {MarketAnalysisHistory:()=>null};
 if(name.includes('/TriangleStepLoader')) return {TriangleStepLoader:()=>null};
 if(name.includes('/ArgusEditorialSurface')) return {ArgusEditorialSurface:()=>null};
 return require(name);
}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/today/MarketBriefCard.tsx','utf8'),
 {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,cardContext);
for(const patch of [{},{presentationStatus:'AWAITING_AI',presentationPlan:null},{presentationStatus:'GENERATED',presentationPlan:{schemaVersion:'invalid'}}]){
 shown={...doc,...patch};assert.equal(valid(shown),true);
 const html=renderToStaticMarkup(React.createElement(cardContext.exports.MarketBriefCard,{editorial:true}));
 assert.ok(html.includes('data-four-cards="visible"')&&html.includes('data-layout="current-four-cards"'));
 assert.ok(!html.includes('at-unified-brief__view'),'current headline comes from the strip');
 assert.equal((html.split('<details>')[0].match(/data-brief-section=/g)||[]).length,3);
 assert.ok(html.includes('自分への影響の根拠'),'all original sections remain in the evidence drawer');
}
const referenceHtml=renderToStaticMarkup(React.createElement(cardContext.exports.MarketBriefCard,{editorial:false}));
assert.ok(!referenceHtml.includes('data-four-cards="visible"'),'reference/archived reading is preserved');
console.log('構成情報が欠けても有効な統合AIを最新４カードで表示 PASS');

// A pending or absent worker is not evidence of a stopped generation.
for (const worker of [undefined, {status:'NOT_RUN'}, {status:'AWAITING_AI'}, {status:'GENERATED'}]) {
 shown={...doc, unifiedStatus:'AWAITING_AI', unifiedSummary:null, generationWorker:worker};
 const html=renderToStaticMarkup(React.createElement(cardContext.exports.MarketBriefCard,{editorial:true}));
 assert.ok(html.includes('見立て待ち'));
 assert.ok(!html.includes('止まっています'));
}
for (const status of ['FAILED','INVALID_RESPONSE','UNAVAILABLE']) {
 shown={...doc, unifiedStatus:'AWAITING_AI', unifiedSummary:null, generationWorker:{status}};
 assert.ok(renderToStaticMarkup(React.createElement(cardContext.exports.MarketBriefCard,{editorial:true}))
  .includes('見立てを作成できませんでした'));
}
assert.equal(cardContext.exports.briefWaitingTitle({...doc,generationWorker:{status:'RUNNING'}}),'見立てを作成中');
recovered=doc;
for (const [status, expected] of [['AWAITING_AI','保存版'],['RUNNING','作成中・保存版'],['FAILED','更新失敗・保存版']]) {
 shown={...doc,unifiedStatus:'AWAITING_AI',unifiedSummary:null,generationWorker:{status}};
 const html=renderToStaticMarkup(React.createElement(cardContext.exports.MarketBriefCard,{editorial:true}));
 assert.ok(html.includes(expected));
 assert.ok(html.includes('data-four-cards="visible"'));
 const aboveCards=html.split('data-four-cards="visible"')[0];
 assert.ok(!aboveCards.includes('見立て待ち') && !aboveCards.includes('要約作成'));
 assert.ok(!html.includes('最新の見立てを取得できません'));
 assert.ok(html.includes('見立ての作成日時'), 'full timestamp remains in the evidence drawer');
}
// 2026-11-13: after the second failed attempt the saved edition is served as
// GENERATED again; the failure the server keeps apart still shows.
recovered=null;
assert.equal(valid({...doc,generationWorker:{status:'GENERATED',lastFailedAt:'2026-09-12T11:00:00Z'}}),true);
assert.equal(valid({...doc,generationWorker:{status:'GENERATED',lastFailedAt:{}}}),false);
for (const [worker, failedShown] of [[{status:'GENERATED',lastFailedAt:'2026-09-12T11:00:00Z'},true],
  [{status:'GENERATED'},false],[{status:'GENERATED',lastFailedAt:null},false]]) {
 shown={...doc,generationWorker:worker};
 const html=renderToStaticMarkup(React.createElement(cardContext.exports.MarketBriefCard,{editorial:true}));
 assert.equal(html.includes('更新失敗・保存版'),failedShown);
 assert.ok(html.includes('data-four-cards="visible"'),'the saved edition itself stays');
}
assert.equal(cardContext.exports.retainedBriefNote({...doc,generationWorker:{status:'RUNNING',lastFailedAt:'2026-09-12T11:00:00Z'}},false),'作成中・保存版');
recovered=doc;
requestFailed=true;
assert.ok(renderToStaticMarkup(React.createElement(cardContext.exports.MarketBriefCard,{editorial:true}))
 .includes('更新確認待ち・保存版'));
console.log('生成待ち・作成中・実際の失敗を区別する表示 PASS');

// A rejected optional layout must not hide a newer, validated six-section edition.
const intentContext={exports:{},Date,Set,Map,URL,require(name){
 if(name==='./marketBrief') return ctx.exports;
 if(name==='./japanMarketComparison') return {validJapanMarketComparison(){throw new Error('unexpected chart in fixture');}};
 return require(name);
}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/presentationIntent.ts','utf8'),
 {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,intentContext);
const intent=intentContext.exports;
const retainedDoc=structuredClone(doc);
retainedDoc.presentationStatus='GENERATED';
retainedDoc.unifiedSummary.sections.view.textJa='以前の市場の見方です。';
retainedDoc.presentationCatalog={contextId:doc.unifiedContext.contextId,inventoryId:'e'.repeat(64),surface:'today',subject:'N225',horizonSessions:5,
 elements:Object.keys(sections).map(id=>({id,kind:'text',payloadId:'f'.repeat(64),evidenceIds:[fact.evidenceId],mandatory:true,urgent:false}))};
retainedDoc.presentationPlan={schemaVersion:'argus-presentation-intent-v1',planId:'d'.repeat(64),contextId:doc.unifiedContext.contextId,
 inventoryId:'e'.repeat(64),surface:'today',subject:'N225',horizonSessions:5,intentJa:'現在の根拠を短く伝える',actionAuthority:false,
 elements:Object.keys(sections).map(id=>({id,purposeJa:'見立てと根拠',placement:id==='view'?'lead':'support',emphasis:id==='view'?'primary':'normal'}))};
assert.equal(intent.hasEditorialIntent(retainedDoc),true);
for(const presentationStatus of ['INVALID_RESPONSE','UNAVAILABLE']) {
 const current=structuredClone(doc);current.generatedAt='2026-09-12T11:00:00Z';
 current.unifiedSummary.sections.view.textJa='AI関連株への売りが日本株にも波及しています。';
 current.presentationStatus=presentationStatus;current.presentationPlan=null;current.retainedPresentation=retainedDoc;
 const unchanged=JSON.stringify(current);
 assert.equal(valid(current),true);
 assert.equal(intent.readableBriefEdition(current),current);
 assert.equal(intent.editorialEdition(current),null,'a valid current summary uses its own fixed layout, not older prose');
 assert.equal(JSON.stringify(current),unchanged,'selection never rewrites saved text, inputs or layout');
 const rejected=structuredClone(current);rejected.unifiedSummary.sections.view.evidenceIds=[old];
 assert.equal(valid(rejected),false);
 assert.equal(intent.readableBriefEdition(rejected).generatedAt,retainedDoc.generatedAt,'invalid text still retains the valid edition');
 assert.equal(intent.editorialEdition(rejected).generatedAt,retainedDoc.generatedAt);
}
assert.equal(intent.editorialEdition(retainedDoc),retainedDoc);
console.log('有効な最新本文を不採用の表示構成で隠さない・無効本文の旧版保持 PASS');
