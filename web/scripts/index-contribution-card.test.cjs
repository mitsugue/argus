// 2026-10-17: the Nikkei 225 contributions inside the shared market card, and
// the owner's factor form that appears only while a factor is needed.
const ts=require('typescript'),fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const load=(path,extra={})=>{
 const module={exports:{},require:req,Date,Number,Array,...extra};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,
  jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,module);
 return module.exports;
};
function req(name){
 if(name.endsWith('.css'))return {};
 if(name.startsWith('../../lib/'))return load(`src/lib/${name.split('/').pop()}.ts`);
 return require(name);
}
const {MarketInternalsCard}=load('src/components/today/MarketInternalsCard.tsx');
const base={status:'AVAILABLE',instrumentId:'INDEX',returnPct:1,startDate:'2026-10-14',endDate:'2026-10-15'};
const doc=(contribution)=>({schemaVersion:'jp-market-internals-v1',evidenceId:'a'.repeat(64),asOfDate:'2026-10-15',actionAuthority:false,
 predictiveProbabilityVerified:false,limitationsJa:[],breadth:{status:'UNAVAILABLE'},periods:{'1':{horizonSessions:1,startDate:base.startDate,
 endDate:base.endDate,index:base,benchmark:base,sectors:[],assets:[],sample:{isWholeMarket:false,counts:{advancers:0,decliners:0,unchanged:0,available:0,expected:0,missing:0}},
 indexContributions:contribution}}});
const html=renderToStaticMarkup(React.createElement(MarketInternalsCard,{document:doc({status:'AVAILABLE',members:225,indexDeltaPoints:300.5,factorsAsOf:'2026-09-30',
 top:[{code:'8035',nameJa:'東京エレクトロン',points:120.5,pricePct:3.1}],bottom:[{code:'9984',nameJa:'ソフトバンクグループ',points:-80.25,pricePct:-2}]}),horizon:1}));
assert.match(html,/日経平均を動かした銘柄/);assert.match(html,/8035 東京エレクトロン/);assert.match(html,/\+120\.50円/);assert.match(html,/-80\.25円/);
assert.match(html,/225銘柄の合計と一致/);assert.doesNotMatch(html,/入力/);
const mismatch=renderToStaticMarkup(React.createElement(MarketInternalsCard,{document:doc({status:'SUM_MISMATCH',reason:'factor_or_divisor_changed'}),horizon:1}));
assert.match(mismatch,/銘柄ごとの値は出していません/);assert.doesNotMatch(mismatch,/押し上げ/);
const focus=renderToStaticMarkup(React.createElement(MarketInternalsCard,{document:doc({status:'AVAILABLE',top:[],bottom:[]}),horizon:1,focusSymbol:'7203'}));
assert.doesNotMatch(focus,/日経平均を動かした銘柄/);
const estimate=renderToStaticMarkup(React.createElement(MarketInternalsCard,{document:doc({status:'AVAILABLE',members:225,indexDeltaPoints:300.5,
 residualPoints:0.8,estimate:true,assumedFactorCodes:['5016','6525','9697'],factorsAsOf:'2026-09-30',top:[{code:'8035',nameJa:'東京エレクトロン',points:120.5,pricePct:3.1}],bottom:[]}),horizon:1}));
assert.match(estimate,/0\.80円以内で一致・概算/);assert.match(estimate,/表にない3銘柄は1\.0と仮定/);
assert.ok(!require('node:fs').existsSync('src/components/today/IndexFactorInput.tsx'),'手入力の欄は無い');
console.log('日経平均の寄与度(手入力なし・概算の表示) PASS');
