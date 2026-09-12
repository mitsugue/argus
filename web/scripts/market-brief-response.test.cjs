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
