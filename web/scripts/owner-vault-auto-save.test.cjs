const assert=require('node:assert/strict'),Module=require('node:module'),path=require('node:path'),esbuild=require('esbuild');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const entry=path.resolve('src/lib/ownerVaultAutoSave.ts');
async function setup(){
 const values=new Map(),h={content:true,saved:false,calls:0,time:1000000,hidden:false,online:true};
 global.__vaultAutoTest=h;global.localStorage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 global.window=new EventTarget();window.setInterval=()=>0;global.document=new EventTarget();Object.defineProperty(document,'hidden',{get:()=>h.hidden});
 Object.defineProperty(global,'navigator',{configurable:true,value:{get onLine(){return h.online},locks:{request:async(_name,_options,fn)=>fn({})}}});
 Date.now=()=>h.time;
 const built=await esbuild.build({entryPoints:[entry],bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent',plugins:[{name:'dependencies',setup(b){
  b.onResolve({filter:/^\.\/(backup|vault|ownerVault)$/},a=>({path:a.path,namespace:'test-dependency'}));
  b.onLoad({filter:/.*/,namespace:'test-dependency'},a=>({contents:a.path==='./backup'?`export const hasBackupContent=()=>globalThis.__vaultAutoTest.content;export const buildBackupPayload=()=>({data:{value:1}});`:a.path==='./vault'?`export const getVaultPass=()=>localStorage.getItem('argus.vaultPass.v1');`:`export const OWNER_VAULT_RECEIPT='receipt';export const alreadySavedForVault=async()=>{const h=globalThis.__vaultAutoTest;if(h.beforeCheck)await h.beforeCheck();return h.saved};export const saveOwnerVault=async(...args)=>{const h=globalThis.__vaultAutoTest;h.calls++;if(h.save)return h.save(...args);h.saved=true;return {savedAt:Date.now()/1000}};`}));
 }}]});const mod=new Module(entry,module);mod.filename=entry;mod.paths=module.paths;mod._compile(built.outputFiles[0].text,entry);
 h.api=mod.exports;h.values=values;h.configure=()=>{values.set(h.api.AUTO_SAVE_CONFIG,'{"enabled":true}');values.set('argus.ownerSyncToken.v1','owner');values.set('argus.vaultPass.v1','pass');};return h;
}
(async()=>{
 const realNow=Date.now;try{
  let h=await setup();await h.api.checkAutoSave();assert.equal(h.calls,0);assert.equal(h.api.autoSaveState().phase,'DISABLED');
  h.configure();h.hidden=true;await h.api.checkAutoSave();assert.equal(h.calls,0);h.hidden=false;h.online=false;await h.api.checkAutoSave();assert.equal(h.api.autoSaveState().phase,'OFFLINE');assert.equal(h.calls,0);
  h.online=true;h.saved=true;h.values.set('receipt','{"savedAt":10}');await h.api.checkAutoSave();assert.equal(h.calls,0);assert.equal(h.api.autoSaveState().lastSuccessAt,10000);
  h.saved=false;await Promise.all([h.api.checkAutoSave(),h.api.checkAutoSave()]);assert.equal(h.calls,1);assert.equal(h.api.autoSaveState().phase,'SAVED');
  h=await setup();h.configure();h.save=async()=>{throw new Error('connection failure')};await h.api.checkAutoSave();assert.equal(h.calls,1);const failure=h.api.autoSaveState().message;h.time+=15000;await h.api.checkAutoSave();assert.equal(h.calls,1);assert.equal(h.api.autoSaveState().phase,'FAILED');assert.equal(h.api.autoSaveState().message,failure);h.time+=300000;h.save=null;await h.api.checkAutoSave();assert.equal(h.calls,2);
  h=await setup();h.configure();h.save=async(_t,_p,_f,_data,signal)=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))));const work=h.api.checkAutoSave();await tick();h.api.disableAutoSave();await work;assert.equal(h.calls,1);assert.equal(h.api.autoSaveState().phase,'DISABLED');h.time+=600000;await h.api.checkAutoSave();assert.equal(h.calls,1);
  h=await setup();h.configure();h.save=async()=>({savedAt:10});await h.api.checkAutoSave();assert.equal(h.api.autoSaveState().phase,'WAITING');h.time+=15000;await h.api.checkAutoSave();assert.equal(h.calls,1);h.time+=120000;await h.api.checkAutoSave();assert.equal(h.calls,2);
  h=await setup();h.configure();let n=0;h.beforeCheck=async()=>{if(++n===2)h.values.set('argus.ownerSyncToken.v1','changed');};await h.api.checkAutoSave();assert.equal(h.calls,0);
  h=await setup();h.configure();navigator.locks.request=async(_name,_options,fn)=>fn(null);await h.api.checkAutoSave();assert.equal(h.calls,0);
  h=await setup();localStorage.setItem=()=>{throw new Error('quota')};assert.throws(()=>h.api.enableAutoSave('owner','pass'),/quota/);assert.equal(h.api.autoSaveEnabled(),false);await h.api.checkAutoSave();assert.equal(h.calls,0);
  console.log('Owner auto save: disabled/hidden/offline/unchanged, one flight, persistent failure and retry, abort, newer edits, credential race, other tab and storage failure PASS');
 }finally{Date.now=realNow;}
})().catch(e=>{console.error(e);process.exit(1)});
