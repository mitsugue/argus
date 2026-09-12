const ts=require('typescript'),fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const context={exports:{},require,Date,Number};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/today/JpyPositionCard.tsx','utf8'),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,context);
const {validJpyPosition,JpyPositionCard}=context.exports;
const document={schemaVersion:'jp-market-jpy-position-v1',status:'AVAILABLE',instrumentId:'JPY',contractCode:'097741',contractSizeJpy:12500000,
 reportType:'LEGACY_FUTURES_ONLY',traderCategory:'NON_COMMERCIAL',unit:'CONTRACTS',actionAuthority:false,observesCurrentLivePositions:false,
 positionDate:'2026-09-08',previousPositionDate:'2026-09-01',receivedAt:'2026-09-12T13:00:00Z',publishedAt:null,positionAgeCalendarDays:4,
 current:{longContracts:100,shortContracts:90,spreadContracts:5,netContracts:10},
 previous:{longContracts:95,shortContracts:92,spreadContracts:6,netContracts:3},
 change:{longContracts:5,shortContracts:-2,spreadContracts:-1,netContracts:7},sourceRef:'https://www.cftc.gov/dea/futures/deacmesf.htm'};
assert.ok(validJpyPosition(document));
for(const patch of [{reportType:'FUTURES_AND_OPTIONS'},{unit:'JPY'},{actionAuthority:true},{observesCurrentLivePositions:true},
 {contractCode:'099741'},{current:{...document.current,netContracts:100}},{change:{...document.change,shortContracts:0}},
 {receivedAt:'unknown'},{positionAgeCalendarDays:-1}]) assert.equal(validJpyPosition({...document,...patch}),false);
const render=document=>renderToStaticMarkup(React.createElement(JpyPositionCard,{document}));
assert.ok(render(document).includes('90枚'));assert.ok(render(document).includes('公表日時'));assert.ok(render(document).includes('未確認'));
assert.ok(render(document).includes('売り建玉がなくなったという意味ではありません'));
assert.ok(render({...document,acquisition:{status:'FAILED'}}).includes('前回取得分'));
assert.ok(render({...document,status:'STALE'}).includes('時間が経過'));
assert.ok(render(null).includes('公式データを確認中'));
console.log('JPY weekly scope, arithmetic, freshness and source display PASS');
