import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import vm from 'node:vm';
// Execute the real scheduler and startup wiring, including queued suspended ticks.
const listeners=new Set(),intervals=new Map(),timeouts=[];let next=0,reads=0;
const document={visibilityState:'visible',addEventListener:(name,fn)=>{assert.equal(name,'visibilitychange');listeners.add(fn);},removeEventListener:(_name,fn)=>listeners.delete(fn)};
const window={setInterval:(fn,ms)=>{intervals.set(++next,{fn,ms});return next;},clearInterval:id=>intervals.delete(id),setTimeout:(fn,ms)=>{timeouts.push({fn,ms});return 1;}};
const sandbox={exports:{},document,window,pollPwaState:()=>{reads++;return Promise.resolve();}};
const policy=fs.readFileSync(new URL('../src/lib/pollingPolicy.ts',import.meta.url),'utf8');
vm.runInNewContext(ts.transpileModule(policy,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,sandbox);
const main=fs.readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8');
const start=main.indexOf('// An ordinary app return retains');assert(start>=0);
const wiring=main.slice(start,main.indexOf('ReactDOM.createRoot',start));
vm.runInNewContext(ts.transpileModule(wiring,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,sandbox);
assert.equal(timeouts.length,1);assert.equal(timeouts[0].ms,4000);timeouts[0].fn();assert.equal(reads,1);
const switchTo=value=>{document.visibilityState=value;for(const fn of [...listeners])fn();};
const queued=[...intervals.values()][0].fn;
for(let i=0;i<10;i++){switchTo('hidden');assert.equal(intervals.size,0);switchTo('visible');assert.equal(intervals.size,1);queued();}
assert.equal(reads,1,'no return or stale timer causes deployed-page/SW acquisition');
const current=[...intervals.values()][0];assert.equal(current.ms,60000);current.fn();assert.equal(reads,2,'ordinary visible update cadence is retained');
assert(!wiring.includes("addEventListener('online'"),'network restoration alone must not recreate the document');
console.log('PASS actual PWA resume wiring: one startup read, ten returns/stale ticks zero reads, normal cadence retained');
