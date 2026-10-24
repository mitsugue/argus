// 日米強弱は日経平均÷S&P500(指数そのもの)の20営業日の変化で見る(2026-10-23)。
// 1321 対 SPY には戻らず、どちらかの指数が無ければ出さない。
const ts=require('typescript'),fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context={exports:{},Number,Map,String};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/nikkeiSp500.ts','utf8'),{
 compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
const {nikkeiSp500Change20Pct}=context.exports;
const day=(n)=>new Date(Date.UTC(2026,7,3+n)).toISOString().slice(0,10);
const bars=(count,close)=>Array.from({length:count},(_,n)=>({date:day(n),close:close(n)}));
// 日経平均が21日で10%上がり、S&P500が横ばいなら比は+10%。
const nikkei=bars(25,(n)=>n>=5?110:100), sp500=bars(25,()=>5000);
assert.ok(Math.abs(nikkeiSp500Change20Pct(nikkei,sp500)-10)<1e-9);
// 両方にある日付だけでそろえる: 米国だけにある日・日本だけにある日は数えない。
const usExtra=[...sp500,{date:'2026-12-31',close:1}];
const jpExtra=[...nikkei,{date:'2027-01-05',close:1}];
assert.ok(Math.abs(nikkeiSp500Change20Pct(jpExtra,usExtra)-10)<1e-9);
// 順番が乱れていても日付順で数える。
assert.ok(Math.abs(nikkeiSp500Change20Pct([...nikkei].reverse(),sp500)-10)<1e-9);
// 足りない・欠けている時は null(推測で埋めない)。
assert.equal(nikkeiSp500Change20Pct(nikkei.slice(0,20),sp500),null);
assert.equal(nikkeiSp500Change20Pct(nikkei,null),null);
assert.equal(nikkeiSp500Change20Pct(null,sp500),null);
assert.equal(nikkeiSp500Change20Pct(nikkei,[]),null);
assert.equal(nikkeiSp500Change20Pct(bars(25,()=>Number.NaN),sp500),null);
assert.equal(nikkeiSp500Change20Pct(nikkei,bars(25,()=>0)),null);
// 画面: 日米強弱は日経平均とS&P500の指数チャートから計算し、1321 の値で埋めない。
const page=fs.readFileSync('src/routes/CommandCenter.tsx','utf8');
assert.match(page,/useIndexChart\('SPX', 'daily'\)/);
// 2026-10-23: 日経平均は検証済みの日経平均そのもの(N225)から読む。
assert.match(page,/const nikkeiIndex = selectedChart\.data\?\.symbol === 'N225' \? selectedChart\.data : null;/);
assert.match(page,/nikkeiSp500Change20Pct\(nikkeiIndex\.indicators\.bars, sp500Index\.data\.indicators\.bars\)/);
assert.ok(!page.includes("headlineEntry('1321')?.relativeStrengthSummary"),'1321 対 SPY の日米強弱に戻さない');
assert.ok(!page.includes('relativeStrength?.nikkei_sp500'),'検証済みETFの比を日米強弱に使わない');
console.log('nikkei-sp500: ok');
