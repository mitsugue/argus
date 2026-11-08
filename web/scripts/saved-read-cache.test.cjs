const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript'),assert=require('node:assert/strict');
const exportsValue={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/savedOverviewCache.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{exports:exportsValue,Map,Date});
const cache=exportsValue.createSavedReadCache(2);
cache.put('owner-session:JP:7203:5:context1','日本株',300000,1000);
assert.equal(cache.get('owner-session:JP:7203:5:context1',1001),'日本株');
for(const key of ['other-session:JP:7203:5:context1','owner-session:US:7203:5:context1','owner-session:JP:7203:20:context1','owner-session:JP:7203:5:context2']) assert.equal(cache.get(key,1001),undefined);
assert.equal(cache.get('owner-session:JP:7203:5:context1',301000),undefined,'期限後は再読取する');
cache.put('a','a',300000,1000);cache.put('b','b',300000,1000);cache.put('c','c',300000,1000);
assert.equal(cache.get('a',1001),undefined,'銘柄数が増えても上限を守る');
assert.equal(cache.get('b',1001),'b');cache.clear();assert.equal(cache.get('c',1001),undefined,'認証変更時に全消去できる');
console.log('銘柄説明: 認証・市場・銘柄・期間・根拠の分離、5分期限、件数上限、消去 PASS');

// Execute the actual saved-reader effect with synthetic time and no network.
{
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ts=require('typescript');
const root=process.cwd();
let now=0,visible=true,calls=0,states=[],effects=[],intervals=new Set(),timeouts=new Set(),listeners=new Map(),requests=[];
const d={get visibilityState(){return visible?'visible':'hidden'},addEventListener:(e,f)=>{if(!listeners.has(e))listeners.set(e,new Set());listeners.get(e).add(f)},removeEventListener:(e,f)=>listeners.get(e)?.delete(f)};
const w={setInterval:f=>{intervals.add(f);return f},clearInterval:f=>intervals.delete(f),setTimeout:f=>{timeouts.add(f);return f},clearTimeout:f=>timeouts.delete(f),addEventListener:()=>{},removeEventListener:()=>{}};
const date=class extends Date{static now(){return now}};
const compile=s=>ts.transpileModule(s,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
function lib(file){const e={};vm.runInNewContext(compile(fs.readFileSync(root+'/src/lib/'+file,'utf8')),{exports:e,Date:date,Map,document:d,window:w});return e;}
const cache=lib('savedOverviewCache.ts'),poll=lib('pollingPolicy.ts');
const react={useState:v=>[typeof v==='function'?v():v,x=>states.push(x)],useEffect:f=>effects.push(f),useSyncExternalStore:()=>true};
const modules={'react':react,'react/jsx-runtime':{jsx:()=>null,jsxs:()=>null},'../../hooks/useMarketBrief':{useMarketBrief:()=>({brief:{unifiedContext:{contextId:'fixed'}}})},'../../lib/ownerSession':{hasOwnerSession:()=>true,subscribeOwner:()=>()=>{}},'../../lib/savedOverviewCache':cache,'../../lib/pollingPolicy':poll,'../../lib/screenNotes':{withoutScreenNotes:x=>x},'./OwnerDialogue':{validJob:v=>v?.status==='SUCCEEDED',OwnerAnswerBody:()=>null},'../common/TriangleStepLoader':{TriangleStepLoader:()=>null},'./OwnerOverview.css':{}};
const e={};vm.runInNewContext(compile(fs.readFileSync(root+'/src/components/dialogue/OwnerOverview.tsx','utf8').replace('import.meta.env.VITE_ARGUS_BACKEND_URL',JSON.stringify('https://saved.test'))),{exports:e,require:n=>{assert.ok(n in modules,n);return modules[n]},Date:date,Number,JSON,RegExp,window:w,document:d,localStorage:{getItem:()=>''},AbortController,fetch:async(u,o)=>{calls++;requests.push(JSON.parse(o.body));return{ok:true,json:async()=>({status:'SUCCEEDED',requestId:'synthetic',overviewRead:{mode:'SAVED_ONLY'},context:{intent:'SUBJECT_OVERVIEW',subject:{symbol:'SYNTHETIC',market:'JP'},horizonSessions:5,baseMarketContextId:'fixed',facts:[]},result:{answer:{sections:{view:{textJa:'説明。'}}}}})}}});
const flush=async()=>{for(let n=0;n<10;n++)await Promise.resolve()};
function mount(){effects=[];e.OwnerOverview({symbol:'SYNTHETIC',market:'JP',horizon:5,line:{fallback:'説明なし'}});return effects.map(f=>f()).filter(f=>typeof f==='function')}
const cleanup=cs=>cs.forEach(f=>f());
async function tick(ms){now+=ms;for(const f of [...intervals])f();await flush()}
(async()=>{let cs=mount();await flush();assert.equal(calls,1);await tick(299999);assert.equal(calls,1,'成功説明の5分内は再読取しない');await tick(1);assert.equal(calls,2,'同じ市場根拠でも5分後に保存した説明を読み直す');cleanup(cs);
cs=mount();await flush();assert.equal(calls,2,'再マウントは有効なメモリ控えを使う');await tick(300000);assert.equal(calls,3,'控えから表示した場合も期限後に再読取する');
visible=false;for(const f of listeners.get('visibilitychange')||[])f();await tick(300000);assert.equal(calls,3,'裏画面では読まない');visible=true;for(const f of listeners.get('visibilitychange')||[])f();assert.equal(calls,3,'復帰だけでは読まない');await tick(30000);assert.equal(calls,4,'復帰後は既存周期で期限を確認する');
cleanup(cs);await tick(300000);assert.equal(calls,4);assert.equal(intervals.size,0);assert.equal(timeouts.size,0);assert.ok(requests.every(x=>x.action==='overview'));console.log('保存説明: 5分内再読取なし・同じ市場根拠で期限後更新・控え表示後更新・裏画面休止・復帰集中なし・後始末・読取限定 PASS');})().catch(x=>{console.error(x);process.exitCode=1});

}
