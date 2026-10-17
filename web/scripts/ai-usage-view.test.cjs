const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),
  {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const {validUsageView,usageCount,usageCost} = require('../src/lib/aiUsageView.ts');
const counts = {records:1,providerCalls:1,unknownProviderCallCount:0,knownEstimatedCostUsd:0,
  unknownCostRecords:1,inputTokens:0,outputTokens:0,cachedInputTokens:0,knownDurationMs:1000,
  unknownDurationRecords:0,retryRecords:0,unknownAttemptRecords:1,
  unknownTokenRecords:{inputTokens:1,outputTokens:1,cachedInputTokens:1},outcomes:{success:1},errorClasses:{}};
const view = {schemaVersion:'argus-owner-usage-view-v1',scope:'OWNER_PRIVATE',generatedAt:'2026-09-13T00:00:00Z',
  monthUtc:'2026-09',timeBasis:'UTC',status:'AVAILABLE',state:{status:'LOCAL_DURABLE',pendingReceipts:0,lastSavedAt:null,lastErrorClass:null},
  rows:[{...counts,feature:'market_brief',provider:'openai',requestedModel:'test',returnedModel:null}],totals:counts,
  throughSequence:1,nextOffset:null,groupCount:1,firstRecordedAt:'2026-09-11T00:00:00Z',lastRecordedAt:'2026-09-11T00:00:00Z',
  remoteRecoveryVerified:false,providerResponseIsContentAcceptance:false,addToLegacyTotal:false,
  coverage:'committed_sdk_receipts_only',historyBeforeFirstReceiptReconstructed:false};
assert(validUsageView(view,'2026-09'));
assert.equal(usageCost(counts),'未取得');assert.equal(usageCount(0,1,1),'未取得');
assert.match(usageCost({...counts,records:2,knownEstimatedCostUsd:.123}),/未取得1件/);
for(const mutate of [v=>v.totals.knownEstimatedCostUsd=NaN,v=>v.scope='PUBLIC',v=>v.monthUtc='2026-08',
 v=>v.totals.unknownCostRecords=2,v=>v.state.pendingReceipts=-1,v=>v.rows[0].inputTokens='0',
 v=>v.rows=Array(51).fill(v.rows[0]),v=>v.addToLegacyTotal=true,v=>v.totals.unknownTokenRecords={},
 v=>v.totals.outcomes.success=2,v=>v.totals.unknownProviderCallCount=1]){
 const invalid=structuredClone(view);mutate(invalid);assert(!validUsageView(invalid,'2026-09'));
}
console.log('Owner AI usage validation and unknown-value presentation PASS');
