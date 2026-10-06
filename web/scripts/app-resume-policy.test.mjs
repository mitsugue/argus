import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const source = fs.readFileSync(new URL('../src/lib/pollingPolicy.ts', import.meta.url), 'utf8');
const output = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {subscribeInitialVisibleRead} = await import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`);
const listeners = new Set();
globalThis.document = {visibilityState:'visible',
  addEventListener: (name, fn) => {assert.equal(name,'visibilitychange');listeners.add(fn);},
  removeEventListener: (name, fn) => {assert.equal(name,'visibilitychange');listeners.delete(fn);}};
const switchTo = state => {document.visibilityState=state;for(const fn of [...listeners]) fn();};
let reads=1; // first acquisition on mount
const stop=subscribeInitialVisibleRead(()=>reads++);
for(let i=0;i<10;i++){switchTo('hidden');switchTo('visible');}
assert.equal(reads,1,'ten app switches must preserve the initial acquisition');
stop();
switchTo('hidden');
const stopDeferred=subscribeInitialVisibleRead(()=>reads++);
assert.equal(listeners.size,1);
switchTo('visible');assert.equal(reads,2,'hidden initial mount reads once when first visible');
switchTo('hidden');switchTo('visible');assert.equal(reads,2);stopDeferred();
switchTo('hidden');const stopCancelled=subscribeInitialVisibleRead(()=>reads++);
stopCancelled();switchTo('visible');assert.equal(reads,2,'unmounted readers must not wake');
// A new document, as produced by manual reload, still performs initial reads.
reads++;const stopReload=subscribeInitialVisibleRead(()=>reads++);
switchTo('hidden');switchTo('visible');assert.equal(reads,3);stopReload();
assert.equal(listeners.size,0);
console.log('PASS app resume: no repeated acquisitions, deferred initial read once, cancellation, reload acquisition');
