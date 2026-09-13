const ts=require('typescript'),fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/marketInternals.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,ctx);
const{selectMarketInternals,validMarketInternals}=ctx.exports;
const base={status:'AVAILABLE',instrumentId:'INDEX',returnPct:-2,startDate:'2026-09-04',endDate:'2026-09-11'};
const frame={schemaVersion:'jp-market-internals-v1',evidenceId:'a'.repeat(64),actionAuthority:false,predictiveProbabilityVerified:false,limitationsJa:[],breadth:{status:'UNAVAILABLE'},periods:{'5':{horizonSessions:5,startDate:base.startDate,endDate:base.endDate,index:base,benchmark:base,sectors:[],assets:[],sample:{isWholeMarket:false,counts:{advancers:0,decliners:0,unchanged:0,available:0,expected:0,missing:0}}}}};
const brief={unifiedSummary:{schemaVersion:'argus-unified-brief-v1',actionAuthority:false,contextId:'b'.repeat(64)},unifiedContext:{contextId:'b'.repeat(64),facts:[{source:'market_internals_calculation',provenance:{eventId:'market-internals-5',sourceRowSha256:frame.evidenceId}}]},calculationSnapshots:{'5':{marketInternals:frame}}};
const latest=structuredClone(frame);latest.evidenceId='c'.repeat(64);latest.periods['5'].index.returnPct=3;
const before=JSON.stringify(brief),chosen=selectMarketInternals(brief,latest,5);
assert.equal(chosen.binding,'AI_SNAPSHOT');assert.equal(chosen.document.periods['5'].index.returnPct,-2);assert.equal(JSON.stringify(brief),before);
for(const mutate of [b=>b.unifiedContext.contextId='d'.repeat(64),b=>b.unifiedContext.facts[0].provenance.sourceRowSha256='e'.repeat(64),b=>b.unifiedContext.facts[0].provenance.eventId='market-internals-20',b=>b.unifiedSummary.actionAuthority=true]) {
 const invalid=structuredClone(brief);mutate(invalid);const result=selectMarketInternals(invalid,latest,5);assert.equal(result.binding,'LATEST_SEPARATE');assert.equal(result.document,latest);
}
assert.equal(selectMarketInternals(brief,latest,20).binding,'LATEST_SEPARATE');
assert.equal(selectMarketInternals(null,latest,5).binding,'AWAITING_AI');
assert.equal(selectMarketInternals(null,{},5).document,null);
const wrong=structuredClone(frame);wrong.periods['5'].sample.counts.expected=1;assert.equal(validMarketInternals(wrong),false);
console.log('Shared market context: exact saved inputs survive newer data; mismatch/horizon/authority stay separate PASS');
