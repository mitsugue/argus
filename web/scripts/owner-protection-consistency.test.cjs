const assert=require('node:assert/strict'),Module=require('node:module'),path=require('node:path'),esbuild=require('esbuild'),crypto=require('node:crypto');
function load(file){const entry=path.resolve(file),code=esbuild.buildSync({entryPoints:[entry],bundle:true,write:false,platform:'node',format:'cjs',define:{__APP_VERSION__:'"test"','import.meta.env':'{}'},logLevel:'silent'}).outputFiles[0].text;const m=new Module(entry,module);m.filename=entry;m.paths=module.paths;m._compile(code,entry);return m.exports;}
const values=new Map();global.localStorage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};global.window=new EventTarget();
(async()=>{
 const safety=load('src/lib/backupSafety.ts'),vault=load('src/lib/ownerVault.ts');values.set('argus.assets.v1','[{"id":"one","quantity":1}]');
 const receipt={snapshotId:'a'.repeat(64),dataHash:crypto.createHash('sha256').update(JSON.stringify({'argus.assets.v1':[{id:'one',quantity:1}]})).digest('hex'),contractVersion:2,savedAt:Date.now()/1000,exportedAt:new Date().toISOString()};
 values.set(vault.OWNER_VAULT_RECEIPT,JSON.stringify(receipt));let result=safety.assessBackupSafety([]);assert.equal(result.storageMode,'owner_encrypted_snapshot');assert.equal(result.protectionLevel,'partially_protected');assert.equal(result.restoreVerified,true);assert.equal(result.protectionLevelJa,'暗号化保存点あり');assert(!result.riskFlags.includes('cloud_push_unavailable'));assert.equal((await vault.ownerVaultProtection()).current,true);
 values.set('argus.assets.v1','[{"id":"one","quantity":2}]');assert.equal((await vault.ownerVaultProtection()).current,false);assert.equal(safety.assessBackupSafety([]).protectionLevel,'partially_protected');
 values.set(vault.OWNER_VAULT_RECEIPT,JSON.stringify({...receipt,contractVersion:1}));assert.notEqual(safety.assessBackupSafety([]).storageMode,'owner_encrypted_snapshot');
 values.set(vault.OWNER_VAULT_RECEIPT,JSON.stringify({...receipt,savedAt:1e100}));assert.equal(await vault.ownerVaultProtection(),null);
 const RealDate=Date;let clock=RealDate.parse('2026-09-14T03:00:00Z');global.Date=class extends RealDate{constructor(value){super(arguments.length?value:clock)}static now(){return clock}};
 try{values.clear();const notifications=load('src/lib/notifications.ts');const input={apItems:[],eventNames:[],flowBySymbol:{},sdBySymbol:{},briefSession:'',hasHoldings:true,snapshotAgeDays:0,vaultConfigured:true,restoreVerified:true,localExportAgeDays:null};
 notifications.runNotificationEngine(input);assert.equal(notifications.listNotifications().filter(n=>n.eventType==='sync_backup_warning').length,1);
 clock+=61000;notifications.runNotificationEngine({...input,ownerSnapshotCurrent:true});assert.equal(notifications.listNotifications().filter(n=>n.eventType==='sync_backup_warning').length,0);
 const stored=JSON.parse(values.get('argus.notifications.v1'));assert(stored.items.some(n=>n.eventType==='sync_backup_warning'&&n.deliveryState==='dismissed'));
 values.delete('argus.notifications.v1');clock+=61000;notifications.runNotificationEngine({...input,ownerSnapshotCurrent:false});assert.equal(notifications.listNotifications().filter(n=>n.eventType==='sync_backup_warning').length,1);
 }finally{global.Date=RealDate;}
 console.log('Owner protection: snapshot-only vs current digest, old/invalid receipts, current-save warning resolution without history deletion, changed content warning PASS');
})().catch(e=>{console.error(e);process.exit(1)});
