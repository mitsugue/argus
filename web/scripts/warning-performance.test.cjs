const ts=require('typescript'), fs=require('node:fs'), assert=require('node:assert/strict');
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
for(const extension of ['.ts','.tsx']) require.extensions[extension]=(mod,filename)=>{
  mod._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,
    target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,filename);
};
const {marketSignalsView}=require('../src/domain/marketSignals.ts');
const {WarningConditionsDetails,warningCoverageJa}=require('../src/components/today/WarningConditionsDetails.tsx');
const at='2026-10-06T00:00:00Z';
const signals=Array.from({length:7},(_,n)=>({id:`WARN-0${n+1}`,family:`D0${n+1}`,
  ruleId:`jp-warning-conditions-v2.D0${n+1}`,state:'DATA_GATED',status:'AVAILABLE',
  ruleStatus:[2,3,6].includes(n)?'RULE_NOT_DEFINED':'DEFINED'}));
signals[4].performance={ruleId:signals[4].ruleId,status:'NOT_ABOVE_BASELINE',evaluated:25,
  horizons:{'5':{evaluated:25,falls:12,baselineFallShare:.49}}};
const projection={informationCutoff:at,warningSignals:{schemaVersion:'jp-warning-conditions-v2',informationCutoff:at,
  rejectedEvidence:false,countPredictsCrash:false,actionAuthority:false,signals}};
const render=()=>renderToStaticMarkup(React.createElement(WarningConditionsDetails,{view:marketSignalsView(projection)}));
assert.ok(render().includes('25件中12件下落・未検証・通常時より予測が優れるとは確認できません'));
assert.ok(render().includes('測定規則の確定後に検査します'));
assert.ok(render().includes('成立件数から暴落の確率は出しません'));
signals[4].performance.ruleId='legacy-v1.D05';
assert.ok(!render().includes('25件中12件'));
signals[4].performance={ruleId:signals[4].ruleId,status:'INSUFFICIENT_SAMPLE',evaluated:3,horizons:{'5':{evaluated:3,falls:2}}};
assert.ok(render().includes('3件中2件下落・未検証・件数不足'));
signals[4].performance.availabilityBasis='RECONSTRUCTED_PUBLICATION_18JST_NOT_ARCHIVED_VINTAGE';
assert.ok(render().includes('過去データを復元した検査：3件中2件下落・未検証・件数不足'));
signals[4].performance.horizons['5'].falls=4;
assert.ok(!render().includes('3件中4件'));
const coverage=warningCoverageJa(marketSignalsView(projection));
assert.equal(coverage.undefinedLabel,'3・4・7');
assert.equal(coverage.measured,0);
assert.equal(coverage.missing.length,4);
signals[0].state='CLEAR'; signals[0].conditionMet=false; signals[0].value=900e9; signals[0].knowledgeTime=at;
signals[1].state='STALE'; signals[1].reasonJa='制度信用の更新待ち';
assert.equal(warningCoverageJa(marketSignalsView(projection)).measured,1);
assert.ok(render().includes('制度信用の更新待ち'));
assert.ok(render().includes('データを取得し直すだけでは判定できません'));
const panel=fs.readFileSync(require.resolve('../src/components/today/ArgusTodayPanel.tsx'),'utf8');
assert.ok(panel.includes('other-analysis-data-status-v1') && panel.includes('登録銘柄・他の分析データの状態'));
console.log('警戒規則の成績: 現行規則の件数、旧規則の除外、件数不足、未定義、不正値の表示抑止 PASS');
