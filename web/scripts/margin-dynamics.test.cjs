const ts=require('typescript'),fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const React=require('react');const {renderToStaticMarkup}=require('react-dom/server');
const context={exports:{},require,Date,Number};vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/today/MarginDynamicsCard.tsx','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,context);
const {validMarginDynamics,MarginDynamicsCard}=context.exports;
const document={schemaVersion:'jp-market-dynamics-v1',instrumentId:'1570',balanceKind:'WEEKLY_MARGIN',actionAuthority:false,observedCoveringOrders:false,predictiveProbability:null,
 current:{periodEnd:'2026-09-04',unit:'UNITS',longBalance:150,shortBalance:15,ratio:10},previous:null,change:{status:'UNAVAILABLE'},sourceRows:[],lastSuccessfulAcquisitionAt:'2026-09-12T01:12:11Z',acquisitionStatus:'AVAILABLE',sourceStatus:'AVAILABLE'};
assert.equal(validMarginDynamics(document),true);
for(const patch of [{actionAuthority:true},{observedCoveringOrders:true},{predictiveProbability:0.5},{lastSuccessfulAcquisitionAt:{}},{sourceRows:[{}]},
 {current:{...document.current,longBalance:NaN}},{current:{...document.current,unit:'JPY'}},{change:{status:'AVAILABLE',ratioChange:{}}}])assert.equal(validMarginDynamics({...document,...patch}),false);
const render=props=>renderToStaticMarkup(React.createElement(MarginDynamicsCard,props));
assert.ok(render({document}).includes('150口'));assert.ok(render({document,refreshFailed:true}).includes('最後に取得できた残高'));
assert.ok(render({document:null}).includes('まだ確認できていません'));
assert.ok(render({document}).includes('買いサインではありません'));assert.ok(render({document}).includes('制度信用'));
// Daily balances after the week end: the latest day and its change since the week end (2026-10-04).
const row=(d,sid,v)=>({periodEnd:d,seriesId:sid,value:v,unit:'UNITS'});
const daily={...document,current:{periodEnd:'2026-09-25',unit:'UNITS',longBalance:1000,shortBalance:100,ratio:10},
 sourceRows:[row('2026-09-25','margin.long_balance',1000),row('2026-09-25','margin.short_balance',100),
  row('2026-10-01','margin.long_balance',1050),row('2026-10-01','margin.short_balance',90)]};
const dailyHtml=render({document:daily});
assert.ok(dailyHtml.includes('最新(日次) 2026-10-01')&&dailyHtml.includes('週末から+50口')&&dailyHtml.includes('週末から-10口'));
assert.ok(dailyHtml.includes('判断の基準は、日次の記録がたまるまで週次のまま'));
assert.ok(!render({document}).includes('最新(日次)'),'no daily line without a later day');
console.log('Margin response validation and failure display PASS');
