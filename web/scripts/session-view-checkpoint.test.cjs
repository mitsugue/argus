const assert=require('node:assert/strict'),Module=require('node:module'),path=require('node:path'),{buildSync}=require('esbuild');
const entry=path.resolve('src/lib/sessionViewCheckpoint.ts');
const code=buildSync({entryPoints:[entry],bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent',define:{'import.meta.env':'{}'}}).outputFiles[0].text;
const mod=new Module(entry,module);mod.filename=entry;mod.paths=module.paths;mod._compile(code,entry);
const {createSessionViewCheckpoint:create}=mod.exports;
const values=new Map();let reads=0,writes=0,fail=false,writeWait=null;
const clone=value=>JSON.parse(JSON.stringify(value));
const storage={read:async key=>{reads++;return clone(values.get(key)??null);},write:async(key,value)=>{writes++;if(writeWait)await writeWait;if(fail)return false;values.set(key,clone(value));return true;}};
const binding={token:'x'.repeat(43),expiresAt:Date.now()+86400000,build:'fixture-build',backendOrigin:'https://fixture-backend.test'};
const original={loading:false,ledger:{asOf:'2026-10-13T06:30:00Z',fixture:'private-view-only'},fetchedAtMs:123456,sessionExpired:true};
const recovery=async(change={},store=storage)=>{const p=create(store);return {cache:p,ok:await p.prepare({...binding,...change},true)};};
(async()=>{
 const a=create(storage);assert.equal(await a.prepare(binding,false),false);assert.equal(reads,0,'a new login/manual reload does not restore cached views');
 assert(a.keep('ledger',original));assert(a.keep('asset:US:TEST:daily',{loading:false,sourceTime:'2026-10-13T01:00:00Z',fixture:'private-asset-only'}));
 assert(await a.flush());assert.equal(values.size,1,'reuse one bounded entry in the existing database');
 const encoded=JSON.stringify([...values.values()]);for(const secret of [binding.token,'private-view-only','private-asset-only','123456'])assert(!encoded.includes(secret),'no plaintext bearer or view value on disk');
 const b=create(storage);let applied;b.bind('ledger',value=>{applied=value;});assert(await b.prepare(binding,true));
 assert.deepEqual(applied,original,'original timestamp/expiry/failure flags are never refreshed by cache restoration');
 assert(b.hasRestored('ledger'));assert(!b.hasRestored('different-subject'));
 let late;const unbind=b.bind('asset:US:TEST:daily',v=>{late=v;});assert.equal(late.sourceTime,'2026-10-13T01:00:00Z');unbind();
 for(const changed of [{token:'z'.repeat(43)},{build:'another-build'},{backendOrigin:'https://another-backend.test'},{expiresAt:binding.expiresAt+1},{expiresAt:Date.now()-1},{token:'short'}]){
  const r=await recovery(changed);assert.equal(r.ok,false);assert.equal(r.cache.hasRestored('ledger'),false);
 }
 const saved=clone(values.get('argus-session-view-v1'));
 for(const field of ['iv','ciphertext']){
  const tampered=clone(saved);tampered[field]=tampered[field].replace(/^./,tampered[field][0]==='A'?'B':'A');
  const r=await recovery({}, {read:async()=>tampered,write:storage.write});assert.equal(r.ok,false,'tampered ciphertext cannot hydrate the view');
 }
 const changedTime=clone(saved);changedTime.savedAt-=1;assert.equal((await recovery({}, {read:async()=>changedTime,write:storage.write})).ok,false,'even a valid-range savedAt change breaks the AEAD binding');
 const stalled=create({read:()=>new Promise(()=>{}),write:storage.write});const started=Date.now();assert.equal(await stalled.prepare(binding,true),false);assert.equal(stalled.diagnostic().status,'storage_timeout');assert(Date.now()-started<2500);
 const future=clone(saved);future.savedAt=Date.now()+86400000;assert.equal((await recovery({}, {read:async()=>future,write:storage.write})).ok,false);
 assert.equal((await recovery({}, {read:async()=>({}),write:storage.write})).ok,false);
 let releaseRead;const reading=create({read:()=>new Promise(resolve=>{releaseRead=resolve;}),write:storage.write});
 let lateLogout=false;reading.bind('ledger',()=>{lateLogout=true;});const pending=reading.prepare(binding,true);reading.clearMemory();releaseRead(saved);
 assert.equal(await pending,false);assert.equal(lateLogout,false);assert.equal(reading.restoredValue('ledger'),undefined);
 let releaseWrite;writeWait=new Promise(resolve=>{releaseWrite=resolve;});
 assert(b.keep('ledger',{...original,fetchedAtMs:200}));const flight=b.flush();
 await new Promise(resolve=>setTimeout(resolve,20));assert(b.keep('ledger',{...original,fetchedAtMs:300}));
 assert.equal(b.flush(),flight,'one in-flight disk write');writeWait=null;releaseWrite();assert(await flight);
 assert.equal((await recovery()).cache.restoredValue('ledger').fetchedAtMs,300);
 const beforeBad=JSON.stringify([...values.values()]);
 assert.equal(b.keep('invalid-number',{x:NaN}),false);assert.equal(b.keep('invalid-function',{x:()=>{}}),false);
 assert.equal(b.keep('oversize','a'.repeat(4*1024*1024+1)),false);assert.equal(JSON.stringify([...values.values()]),beforeBad);
 assert(b.keep('ledger',{...original,fetchedAtMs:400}));fail=true;assert.equal(await b.flush(),false);fail=false;assert(await b.flush());
 assert.equal((await recovery()).cache.restoredValue('ledger').fetchedAtMs,400);
 b.clearMemory();assert.equal(b.keep('ledger',original),false);assert.equal(await b.flush(),false);
 const bounded=create(storage);await bounded.prepare(binding,false);for(let i=0;i<64;i++)assert(bounded.keep('key:'+i,{loading:false}));
 assert.equal(bounded.keep('key:65',{}),false,'do not silently drop a view or expand capacity');
 console.log('PASS actual AES-GCM/HKDF encrypted view checkpoint: same existing storage, exact session/build/origin/expiry, original data times, tamper/expiry/logout rejection, one writer, concurrent updates and bounds; no fetch or credential persistence');
})().catch(error=>{console.error(error);process.exitCode=1;});
