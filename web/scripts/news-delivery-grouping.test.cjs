const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText, filename);
const {groupRepeatedNewsHeadlines, orderMaterialNews} = require('../src/domain/newsPresentation.ts');
const {newsAnalysisStatusJa,newsIntakeHealthJa}=require('../src/lib/newsHeadline.ts');
assert.equal(newsAnalysisStatusJa('ANALYZED','mail_headline_and_bounded_excerpt'),'見出し・抜粋を解析');
assert.equal(newsAnalysisStatusJa('ANALYZED','stored_headline_only'),'見出しを解析・本文未確認');
assert.equal(newsAnalysisStatusJa('ANALYZED'),'解析範囲は未確認');
assert.equal(newsAnalysisStatusJa('AI_CACHED','stored_headline_only'),'見出しを解析・本文未確認（保存分）');
const now=Date.parse('2026-10-05T01:00:00Z');
const health={status:'HEALTHY',lastSyncAt:'2026-10-05T00:59:00Z',configured:true,threadAlive:true,pending:0};
assert.equal(newsIntakeHealthJa(health,now),'新着を確認済み');
assert.equal(newsIntakeHealthJa({...health,pending:2},now),'新着 2件を整理中');
assert.equal(newsIntakeHealthJa({...health,lastSyncAt:'2026-10-05T00:40:00Z'},now),'新着確認が15分以上遅れています');
assert.equal(newsIntakeHealthJa({...health,status:'DEGRADED'},now),'取り込みに不具合があります');
assert.equal(newsIntakeHealthJa({...health,lastSyncAt:null},now),'取り込み時刻は未確認');
assert.equal(newsIntakeHealthJa({...health,threadAlive:false},now),'取り込み処理が停止中');
assert.equal(newsIntakeHealthJa(null,now),'取り込み状態は未確認');
const older={eventId:'delivery-a',revision:1,severity:'HIGH',source:'Official News',
  headlineJa:'政策見通しを更新',sourceReceivedAt:'2026-09-15T22:00:00Z',
  eventMemory:{episodeId:'episode-a'}};
const newer={...older,eventId:'delivery-b',sourceReceivedAt:'2026-09-16T03:00:00Z'};
const original=JSON.stringify([older,newer]);
let groups=groupRepeatedNewsHeadlines([older,newer]);
assert.equal(groups.length,1);
assert.equal(groups[0].lead.eventId,'delivery-b');
assert.deepEqual(groups[0].previous.map(x=>x.eventId),['delivery-a']);
assert.equal(JSON.stringify([older,newer]),original);
for(const change of [{source:'Other publisher'},{headlineJa:'政策決定の続報'},
  {eventMemory:null},{eventMemory:{episodeId:'unrelated'}},
  {sourceReceivedAt:'2026-09-17T03:00:00Z'},{sourceReceivedAt:null}]) {
  assert.equal(groupRepeatedNewsHeadlines([older,{...newer,...change}]).length,2);
}
groups=groupRepeatedNewsHeadlines([older,newer,{...newer,revision:2,severity:'INFO'}]);
assert.equal(groups[0].lead.severity,'INFO');
assert.equal(orderMaterialNews(groups.map(g=>g.lead)).length,0,'a later correction can lower importance');
assert.equal(groups[0].previous.length,1,'same-ID revisions do not create a duplicate delivery');
assert.equal(groupRepeatedNewsHeadlines([{...older,headlineJa:'　政策見通しを更新　'},newer]).length,1);
console.log('PASS: same episode/publisher/JST-day/headline folds to latest delivery, old records retained, unrelated events remain separate');
