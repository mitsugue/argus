// Today's "市場の現在位置" card: themes with entries first, measured pricing and the next check,
// nothing rendered without the server memory, and no forecast wording.
const ts=require('typescript'),fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const req=(name)=> {
 if(name.endsWith('.css')) return {};
 if(name.startsWith('../../lib/')) {
  const module={exports:{},require:req,Date,Number,Array};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(`src/lib/${name.split('/').pop()}.ts`,'utf8'),{
   compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,module);
  return module.exports;
 }
 return require(name);
};
const context={exports:{},require:req,Date,Number,Array};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/today/MarketPositionCard.tsx','utf8'),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,context);
const {MarketPositionCard}=context.exports;
const render=brief=>renderToStaticMarkup(React.createElement(MarketPositionCard,{brief}));
const theme=(over)=>({themeId:'US_POLICY_RATE',labelJa:'米国の利上げ・利下げ観測',status:'ACTIVE',entryCount:3,lastUpdatedAt:'2026-10-02T12:35:00Z',
 recent:[{entryId:'e1',kind:'RELEASE_REACTION',at:'2026-10-02T12:35:00Z',textJa:'米雇用統計の発表+5m: 利上げ観測の後退を安心材料に株高',severity:'HIGH'},
         {entryId:'e2',kind:'NEWS',at:'2026-09-28T13:00:00Z',textJa:'FRB: 年内の追加利上げを示唆',severity:'HIGH'}],
 pricing:{ffImpliedRatePct:3.93},lastReaction:{at:'2026-10-02T12:35:00Z',textJa:'米雇用統計の発表+5m: 利上げ観測の後退を安心材料に株高',readingCode:'RATE_RELIEF_RISK_ON'},
 nextEvent:{title:'米CPI',eventTimeUtc:'2026-10-14T12:30:00Z',eventCode:'CPI'},...over});
const base={schemaVersion:'x',generatedAt:'2026-10-03T02:00:00Z',now:'',why:'',next:'',aiText:null,aiModel:null,chips:{chart:'',news:'',nextEvent:'',mainRisk:''},facts:[],noteJa:'',sdaAuthority:false};
// No server memory: nothing is rendered (the brief predates the server release or failed).
assert.equal(render(base),'');
assert.equal(render({...base,marketPosition:{status:'UNAVAILABLE',errorClass:'ValueError'}}),'');
const position={schemaVersion:'argus-market-position-memory-v1',asOf:'2026-10-03T02:00:00Z',entryCount:3,actionAuthority:false,automaticAiCalls:0,
 themes:[theme({themeId:'JPY',labelJa:'円相場',status:'EMPTY',entryCount:0,recent:[],pricing:null,lastReaction:null,nextEvent:null}),theme()]};
const html=render({...base,marketPosition:position});
assert.ok(html.includes('市場の現在位置')&&html.includes('2テーマ中 1件に更新'));
assert.ok(html.includes('政策金利の予想(FF先物) 3.930%'));
assert.ok(html.includes('次: 米消費者物価')&&html.includes('10/14'));
assert.ok(html.includes('利上げ観測の後退を安心材料に株高')&&html.includes('発表の反応'));
assert.ok(html.indexOf('米国の利上げ・利下げ観測')<html.indexOf('円相場'),'themes with entries come first');
assert.ok(html.includes('14日以内に記録あり')&&html.includes('記録なし'));
assert.ok(html.includes('data-entry-count="3"'));
for(const banned of ['確率','買い','売り','BUY']) assert.ok(!html.includes(banned),banned);
// The integrated AI's view (expectation / fear / trigger) is shown as an inference, above the records.
const withView={...position,themes:[theme({view:{expectationJa:'弱い雇用で追加利上げは見送られるとの見方',fearJa:'次の物価指標が強ければ利上げ観測が戻る',
 triggerJa:'次の物価指標と次回会合の示唆',at:'2026-10-03T02:10:00Z',kind:'INFERENCE'}})]};
const viewHtml=render({...base,marketPosition:withView});
assert.ok(viewHtml.includes('市場の期待')&&viewHtml.includes('市場の警戒')&&viewHtml.includes('次の確認点'));
assert.ok(viewHtml.includes('警戒: 次の物価指標が強ければ')&&viewHtml.includes('ARGUSの整理(推論)'));
assert.ok(viewHtml.indexOf('mp-view')<viewHtml.indexOf('mp-entries'),'the view comes before the records');
assert.ok(!html.includes('市場の期待'),'no view block without a view');
console.log('Market position card PASS');
// AIの連結した記録を閉じたカードの要約に再利用しない。
const duplicated=theme({lastReaction:null,recent:[{entryId:'ai',kind:'AI_VIEW',at:'2026-10-04T12:00:00Z',textJa:'期待: 重複する要約 / 警戒: 重複する要約',severity:'INFO'}],
 view:{expectationJa:'市場が期待する具体的な展開は、現在の根拠では確認できません。',fearJa:'市場が警戒する具体的な展開は、現在の根拠では確認できません。',triggerJa:'次の報道を確認'}});
const pending=render({...base,marketPosition:{...position,themes:[duplicated]}});
const summary=pending.split('</summary>')[0];
assert.ok(!summary.includes('重複する要約'));
assert.ok(summary.includes('期待・警戒の判断材料が不足しています'));
const wording=req('../../lib/marketWording');
assert.ok(wording.marketWording('米消費者物価（2026-10-14・12:30Z）').includes('10/14 21:30'));
assert.ok(wording.marketWording('次回（2026-10-14T23:30:00Z）').includes('10/15 08:30'));
assert.equal(wording.marketWording('金利3.930%'), '金利3.930%');
assert.equal(wording.hasSubstantiveView('現在の根拠では確認できません'),false);
const quiet=render({...base,marketPosition:{...position,themes:[theme({status:'QUIET'})]}});
assert.ok(quiet.includes('14日間、新しい記録なし')&&quiet.includes('更新待ち'));
