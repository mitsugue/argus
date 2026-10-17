import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const bundle=(await build({entryPoints:[path.join(web,'src/hooks/useJapanWatchlist.ts')],bundle:true,write:false,
  platform:'node',format:'esm',define:{'import.meta.env':JSON.stringify({VITE_ARGUS_BACKEND_URL:'https://synthetic.invalid'})},
  plugins:[{name:'isolated-quote-consumer',setup(b){
    b.onResolve({filter:/^react$/},()=>({path:'react',namespace:'quote-test'}));
    b.onResolve({filter:/sessionViewCheckpoint$/},()=>({path:'checkpoint',namespace:'quote-test'}));
    b.onLoad({filter:/.*/,namespace:'quote-test'},({path:p})=>({contents:p==='react'
      ? 'export function useSyncExternalStore(subscribe,get){globalThis.quoteHarness.get=get;globalThis.quoteHarness.stops.push(subscribe(()=>{}));return get();}'
      : 'export const sessionViewCheckpoint={bind(){},hasRestored(){return false},keep(){return false},flush:async()=>{}};'}));
  }}],logLevel:'silent'})).outputFiles[0].text;
const saved={document:globalThis.document,window:globalThis.window,fetch:globalThis.fetch,now:Date.now};
let now=Date.parse('2026-10-14T01:47:45Z');let id=0;const intervals=new Map(),timeouts=new Map(),visible=new Set();
let dynamicReads=0,curatedReads=0,historyReads=0;
globalThis.quoteHarness={get:null,stops:[]};
globalThis.document={hidden:false,visibilityState:'visible',addEventListener:(n,f)=>visible.add(f),removeEventListener:(n,f)=>visible.delete(f)};
globalThis.window={setInterval:(f,ms)=>{const key=++id;intervals.set(key,{f,ms});return key;},clearInterval:k=>intervals.delete(k),
  setTimeout:(f,ms)=>{const key=++id;timeouts.set(key,{f,ms});return key;},clearTimeout:k=>timeouts.delete(k)};
Date.now=()=>now;
globalThis.fetch=async url=>{
  assert.match(url,/^https:\/\/synthetic\.invalid\/api\/argus\//);
  const doc={provider:'TACHIBANA',enabled:true,displayApproved:true,mode:'DISPLAY',shadowOnly:true,
    authoritative:false,status:'STALE',providerHealth:'AVAILABLE',cashSessionOpen:true,readAt:new Date(now).toISOString(),
    quoteRequestedSymbols:['8058'],symbols:{'8058':{provider:'TACHIBANA',price:123.4+dynamicReads,
      sourceTimestamp:new Date(Math.floor(now/60_000)*60_000).toISOString(),sourceTimestampPrecision:'MINUTE',
      receivedAt:new Date(now-1000).toISOString(),marketStatus:'OPEN',freshness:'DELAYED',realtimeClassification:'CURRENT_MARKET_SNAPSHOT'}}};
  if(url.includes('price-history')){historyReads++;throw Error('unexpected price-history');}
  if(url.includes('?symbols=')){dynamicReads++;return{ok:true,json:async()=>({status:'mock',asOf:null,stocks:[],japaneseLive:doc})};}
  curatedReads++;return{ok:true,json:async()=>({status:'delayed',asOf:'2026-10-13',stocks:[{symbol:'8058',name:'合成検査銘柄',
    price:100.01,changeAbs:0.01,changePct:0.01,volume:100,date:'2026-10-13',sourceTimestamp:'2026-10-13',receivedAt:'2026-10-13T07:00:00Z',status:'delayed'}]})};
};
const settle=async()=>{for(let n=0;n<4;n++)await new Promise(resolve=>setImmediate(resolve));};
try{
 const mod=await import('data:text/javascript;base64,'+Buffer.from(bundle).toString('base64'));
 mod.useJapanWatchlist(['8058']);mod.useJapanWatchlist(['8058']);await settle();
 assert.equal(dynamicReads,1);assert.equal(curatedReads,1);assert.equal(intervals.size,1);
 assert.equal([...intervals.values()][0].ms,10_000,'accepted price response changes the one reader immediately');
 const original=globalThis.quoteHarness.get().data.stocks[0];assert.equal(original.price,100.01);assert.equal(original.sourceTimestamp,'2026-10-13');
 for(let n=0;n<6;n++){now+=10_000;for(const timer of [...intervals.values()])timer.f();await settle();}
 assert.equal(dynamicReads,7);assert.equal(curatedReads,1);assert.equal(historyReads,0);
 assert.equal(globalThis.quoteHarness.get().data.stocks[0].receivedAt,original.receivedAt);
 assert.equal(globalThis.quoteHarness.get().data.stocks[0].sourceTimestamp,original.sourceTimestamp);
 assert.equal(globalThis.quoteHarness.get().data.stocks[0].price,100.01,'reference transport must not replace analysis baseline');
 assert.equal(intervals.size,1);
 for(let n=0;n<6;n++){now+=10_000;for(const timer of [...intervals.values()])timer.f();await settle();}
 assert.equal(curatedReads,2,'EOD fallback keeps the original two-minute budget');
 const beforeHide=dynamicReads;document.hidden=true;document.visibilityState='hidden';for(const f of [...visible])f();
 assert.equal(intervals.size,0);now+=45_000;document.hidden=false;document.visibilityState='visible';for(const f of [...visible])f();await settle();
 assert.equal(dynamicReads,beforeHide,'ordinary return must not read immediately');assert.equal(intervals.size,1);
 now+=10_000;for(const timer of [...intervals.values()])timer.f();await settle();assert.equal(dynamicReads,beforeHide+1);
 for(const stop of globalThis.quoteHarness.stops)stop();assert.equal(intervals.size,0);assert.equal(timeouts.size,0);
 console.log('JP price runtime: two consumers share one timer, active10s, EOD120s, original times, hidden0 and return0 PASS');
}finally{for(const stop of globalThis.quoteHarness.stops)stop();Date.now=saved.now;
 for(const k of ['document','window','fetch'])if(saved[k]===undefined)delete globalThis[k];else globalThis[k]=saved[k];delete globalThis.quoteHarness;}
