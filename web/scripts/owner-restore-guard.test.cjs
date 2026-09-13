const assert=require('node:assert/strict'),Module=require('node:module'),path=require('node:path'),esbuild=require('esbuild');
(async()=>{
 const entry=path.resolve('src/lib/ownerRestoreGuard.ts');const h={current:false,content:true,saves:0,stops:0};global.__restoreGuard=h;
 const values=new Map();global.localStorage={getItem:k=>values.get(k)??null};
 const code=await esbuild.build({entryPoints:[entry],bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent',plugins:[{name:'dependencies',setup(b){
 b.onResolve({filter:/^\.\/(backup|vault|ownerVault|ownerVaultAutoSave)$/},a=>({path:a.path,namespace:'test'}));
 b.onLoad({filter:/.*/,namespace:'test'},a=>({contents:a.path==='./backup'?`export const hasBackupContent=()=>globalThis.__restoreGuard.content;`:a.path==='./vault'?`export const getVaultPass=()=>localStorage.getItem('pass');`:a.path==='./ownerVaultAutoSave'?`export const AUTO_SAVE_CONFIG='auto';export const disableAutoSave=()=>{globalThis.__restoreGuard.stops++};`:`export const OWNER_VAULT_RECEIPT='receipt';export const ownerVaultProtection=async()=>({current:globalThis.__restoreGuard.current});export const saveOwnerVault=async()=>{const h=globalThis.__restoreGuard;h.saves++;if(h.fail)throw new Error('save failed');h.current=!h.changedDuringSave;};`}));
 }}]});const mod=new Module(entry,module);mod.filename=entry;mod.paths=module.paths;mod._compile(code.outputFiles[0].text,entry);const guard=mod.exports.preserveBeforeOwnerRestore;
 assert.equal(await guard(()=>{}),false);assert.equal(h.stops,0);
 values.set('auto','{}');h.content=false;assert.equal(await guard(()=>{}),true);assert.equal(h.saves,0);
 h.content=true;h.current=true;assert.equal(await guard(()=>{}),true);assert.equal(h.saves,0);
 h.current=false;await assert.rejects(guard(()=>{}),/現在の変更を先に/);assert.equal(h.saves,0);
 values.set('argus.ownerSyncToken.v1','owner');values.set('pass','pass');assert.equal(await guard(()=>{}),true);assert.equal(h.saves,1);
 h.current=false;h.fail=true;await assert.rejects(guard(()=>{}),/save failed/);h.fail=false;h.changedDuringSave=true;await assert.rejects(guard(()=>{}),/退避中にデータが変わりました/);
 console.log('Owner restore guard: old workflow, empty/current data, missing credentials, preserved edits, failed save and concurrent edits PASS');
})().catch(e=>{console.error(e);process.exit(1)});
