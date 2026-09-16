const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText, filename);
const {groupRepeatedNewsHeadlines, orderMaterialNews} = require('../src/domain/newsPresentation.ts');
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
