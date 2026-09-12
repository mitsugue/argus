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
console.log('Margin response validation and failure display PASS');
