const fs=require('node:fs'),ts=require('typescript'),vm=require('node:vm'),assert=require('node:assert/strict');
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const context={exports:{},URL,require:name=>name.endsWith('.css')?{}:require(name)};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/today/CreditConditionsDetails.tsx','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,context);
const doc={schemaVersion:'credit-conditions-v1',snapshotId:'a'.repeat(64),actionAuthority:false,showToday:true,
 dimensions:{borrowingCost:{status:'OBSERVED',direction:'RISING',value:1.5,unit:'PERCENT',dataAsOf:'2026-08-31'},creditQuality:{status:'INSUFFICIENT_DATA'}},
 evidence:[{observationId:'b'.repeat(64),title:'貸出金利',value:1.5,unit:'PERCENT',dataAsOf:'2026-08-31',publicationDate:null,publicationAt:null,
 retrievedAt:'2026-10-08T01:00:00Z',validationStatus:'VERIFIED',revision:0,tablePageFigureRef:'公式系列の参照',sourceUrl:'https://www.boj.or.jp/',publisher:'日本銀行'}],
 sourceHealth:[{sourceId:'boj_credit_cost',publisher:'日本銀行',status:'STALE',cadence:'MONTHLY',count:2},{sourceId:'joint_data_platform',publisher:'金融庁・日本銀行',status:'NOT_ACQUIRED'}]};
const render=creditConditions=>renderToStaticMarkup(React.createElement(context.exports.CreditConditionsDetails,{brief:{creditConditions}}));
const html=render(doc);
for(const text of ['信用環境：','貸出金利は上昇','比較できる数値が不足','古い値・更新待ち','公表時刻 未確認','受領 2026/10/8','全体の分類は未検証','毎日の売買タイミング','予測の入力・成績は変更していません']) assert.ok(html.includes(text),text);
assert.ok(!render({...doc,showToday:false}).includes('信用環境：'),'unchanged data remains in the evidence drawer');
assert.equal(render({...doc,actionAuthority:true}),'');assert.equal(render(undefined),'');
assert.ok(!render({...doc,evidence:[{...doc.evidence[0],sourceUrl:'javascript:alert(1)'}]}).includes('javascript:'));
assert.ok(!fs.readFileSync('src/components/today/CreditConditionsDetails.tsx','utf8').includes('fetch('));
console.log('信用環境：不足・古さ・出典・条件付き表示・外部取得なし PASS');

assert.ok(render({...doc,collectionStatus:'FAILED',showToday:false}).includes('信用環境の更新に失敗しました。受領済みの保存値を表示しています。'));
