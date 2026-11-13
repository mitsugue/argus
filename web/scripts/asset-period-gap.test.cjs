const assert = require('node:assert/strict'), fs = require('node:fs'), ts = require('typescript'), vm = require('node:vm');
const ctx = { exports: {}, Number };
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/assetPeriodGap.ts', 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, ctx);
const f = ctx.exports.assetPeriodGapJa;
// The production frame of 2026-11-13 for 5803 (values from the saved market brief).
const row = { relativeToNikkeiPct: -7.490813909757421, relativeToSectorPct: -8.329910845248257,
  sectorNameJa: '鉄鋼・非鉄', startDate: '2026-11-05', endDate: '2026-11-12' };
assert.equal(f(row, 5), '日経との差 -7.49% · 鉄鋼・非鉄との差 -8.33%（11/5〜11/12・5営業日）');
assert.equal(f({ ...row, relativeToSectorPct: null }, 5), '日経との差 -7.49%（11/5〜11/12・5営業日）');
assert.equal(f({ ...row, sectorNameJa: null }, 5), '日経との差 -7.49%（11/5〜11/12・5営業日）', 'no sector name, no sector gap');
assert.equal(f({ ...row, relativeToNikkeiPct: null }, 5), '鉄鋼・非鉄との差 -8.33%（11/5〜11/12・5営業日）');
assert.equal(f({ ...row, relativeToNikkeiPct: null, relativeToSectorPct: null }, 5), null);
assert.equal(f({ ...row, relativeToNikkeiPct: 1.234 }, 5).startsWith('日経との差 +1.23%'), true);
assert.equal(f({ ...row, startDate: 'bad' }, 5), '日経との差 -7.49% · 鉄鋼・非鉄との差 -8.33%（5営業日）');
assert.equal(f(null, 5), null);
const panel = fs.readFileSync('src/components/assetDesk/AssetNumbers.tsx', 'utf8');
assert.ok(panel.includes('assetPeriodGapJa(row, 5)'), 'the stock page uses the period line');
console.log('個別銘柄: 日経と業種との差を、期間つきで1行に PASS');
// 2026-11-13 (owner): the stock page has no 結論 and no AI view (the same as Today).
{
  const card = fs.readFileSync('src/components/assetDesk/AssetDecisionCard.tsx', 'utf8');
  assert.ok(!card.includes('OwnerOverview'), 'no stock AI view on the stock page');
  assert.ok(!card.includes('>結論<'), 'no 結論 block');
  assert.ok(card.includes("sectionAnchorId(sym, 'decision')") && card.includes('<AssetNikkeiGap d={d} />'),
    'the gap line and the decision anchor stay');
  console.log('個別銘柄: 結論とAIの見立てを外し、差の行と行き先は残す PASS');
}
