import { BACKUP_CONTRACT_VERSION, buildBackupPayload, assertBackupHistoryReadable, verifyBackupRoundTrip, type BackupFile } from './backup';
import {encryptBackup,decryptBackup,vaultIdFrom} from './vault';
import {OWNER_VAULT_RECEIPT,readOwnerVaultReceipt} from './ownerVaultReceipt';
export {OWNER_VAULT_RECEIPT} from './ownerVaultReceipt';
export type VaultSnapshot={snapshotId:string;bytes:number;savedAt:number;exportedAt:string};
export async function digest(value:string){const raw=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));return Array.from(new Uint8Array(raw),b=>b.toString(16).padStart(2,'0')).join('');}
export async function vaultRequest(token:string,vaultId:string,operation:string,fields:Record<string,unknown>={},signal?:AbortSignal){
  const base=(import.meta.env.VITE_ARGUS_BACKEND_URL as string|undefined)?.replace(/\/$/,'');
  if(!base)throw new Error('保存先に接続できません。');
  signal?.throwIfAborted();const abort=new AbortController();const forward=()=>abort.abort();signal?.addEventListener('abort',forward,{once:true});const timer=setTimeout(()=>abort.abort(),190000);
  try{
    const result=await fetch(base+'/api/argus/owner-dialogue',{method:'POST',cache:'no-store',signal:abort.signal,
      headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'vault',operation,ownerToken:token,vaultId,...fields})});
    if(!result.ok){const data=await result.json();throw new Error(result.status===401||result.status===403?'所有者の接続キーを確認してください。':
      data.error==='vault_private_repository_required'?'保存先が非公開であることを確認できません。':
      data.error==='vault_size_bound'?'この保存点は8 MiBの上限を超えています。データは削除していません。':
      data.error==='vault_staging_full'?'未完了の送信が残っています。保存状態の確認が必要です。':'暗号化保存先との通信を確認できませんでした。');}
    return await result.json();
  }finally{clearTimeout(timer);signal?.removeEventListener('abort',forward);}
}
async function saveOwnerVaultUnlocked(token:string,pass:string,onProgress:(message:string)=>void,payload:BackupFile,signal?:AbortSignal):Promise<VaultSnapshot>{
  signal?.throwIfAborted();
  if(!pass)throw new Error('暗号化のパスフレーズを入力してください。');
  assertBackupHistoryReadable(payload);
  if(!verifyBackupRoundTrip(payload).passed)throw new Error('保存データの復元検査を通過していません。元データは変更していません。');
  const vaultId=await vaultIdFrom(pass);const dataHash=await digest(JSON.stringify(payload.data));
  let pending=await pendingVault(vaultId);let blob:string;
  if(pending&&pending.dataHash!==dataHash){
    // Finish the existing immutable point before staging a newer edit.
    const previous=await decryptBackup(pass,pending.blob);
    if(await digest(JSON.stringify(previous.data))!==pending.dataHash)throw new Error('送信待ちデータの照合に失敗しました。');
    await saveOwnerVaultUnlocked(token,pass,onProgress,previous,signal);pending=undefined;
  }
  if(pending?.dataHash===dataHash){blob=pending.blob;payload=await decryptBackup(pass,blob);assertBackupHistoryReadable(payload);if(await digest(JSON.stringify(payload.data))!==dataHash)throw new Error('送信待ちデータの照合に失敗しました。');}
  else{blob=await encryptBackup(pass,payload);}
  const bytes=new TextEncoder().encode(blob).length;
  if(bytes>8*1024*1024)throw new Error('暗号化後のデータが8 MiBを超えています。元データは変更していません。');
  const snapshotId=await digest(blob);
  // The v1 encrypted envelope is ASCII; split by bytes without changing encryption.
  if(blob.length!==bytes)throw new Error('暗号化したデータの形式を確認できません。');
  signal?.throwIfAborted();
  if(!pending)await pendingVault(vaultId,{vaultId,dataHash,blob});
  const begin=await vaultRequest(token,vaultId,'begin',{snapshotId,bytes},signal);
  if(begin.chunkBytes!==16000||!Array.isArray(begin.parts))throw new Error('保存先の転送形式を確認できません。');
  if(begin.state!=='VERIFIED'){
    const completed=new Set<number>(begin.parts);const count=Math.ceil(bytes/16000);
    for(let offset=0;offset<count;offset+=4){const results=await Promise.allSettled(Array.from({length:Math.min(4,count-offset)},async(_,i)=>{
      const part=offset+i;if(!completed.has(part))await vaultRequest(token,vaultId,'chunk',{snapshotId,part,data:blob.slice(part*16000,(part+1)*16000)},signal);
    }));const failure=results.find((result):result is PromiseRejectedResult=>result.status==='rejected');if(failure)throw failure.reason;
      onProgress(`暗号化データを転送中 ${Math.min(count,offset+4)}/${count}`);}
    let state=await vaultRequest(token,vaultId,'commit',{snapshotId},signal);const deadline=Date.now()+210000;
    while(state.state!=='VERIFIED'){
      if(state.state==='FAILED'||state.state==='INTERRUPTED'||Date.now()>deadline)throw new Error(state.error==='vault_catalog_full_existing_snapshots_retained'
        ?'保存点が2,000件の上限に達しました。既存の履歴と現在の端末データは保持しています。保存先の対応が必要です。'
        :'遠隔保存を確認できていません。現在の端末データはそのままです。');
      onProgress('非公開の保存先へ記録し、内容を読み戻しています。');
      await new Promise(resolve=>setTimeout(resolve,2000));state=await vaultRequest(token,vaultId,'status',{snapshotId},signal);
    }
  }
  onProgress('保存点を読み戻し、この端末で復号して照合しています。');
  const restored=await readOwnerVault(token,pass,snapshotId,signal);
  if(JSON.stringify(restored)!==JSON.stringify(payload))throw new Error('復号後の内容が一致しません。保存成功として記録していません。');
  signal?.throwIfAborted();
  const receipt={snapshotId,bytes,savedAt:Date.now()/1000,exportedAt:payload.exportedAt};
  try{localStorage.setItem(OWNER_VAULT_RECEIPT,JSON.stringify({...receipt,vaultId,contractVersion:BACKUP_CONTRACT_VERSION,dataHash:await digest(JSON.stringify(payload.data))}));}catch{/* Remote proof still exists. */}
  await pendingVault(vaultId,null);
  window.dispatchEvent(new CustomEvent('argus:vault-saved'));
  return receipt;
}
export async function readOwnerVault(token:string,pass:string,snapshotId:string,signal?:AbortSignal):Promise<BackupFile>{
  if(!/^[a-f0-9]{64}$/.test(snapshotId))throw new Error('保存点の識別情報が不正です。');
  const value=await vaultRequest(token,await vaultIdFrom(pass),'read',{snapshotId},signal);
  if(value.snapshotId!==snapshotId||typeof value.blob!=='string'||value.blob.length>8*1024*1024||await digest(value.blob)!==snapshotId)
    throw new Error('保存点の内容を検証できません。');
  const payload=await decryptBackup(pass,value.blob);
  if(payload.app!=='argus'||!payload.data||typeof payload.data!=='object'||Array.isArray(payload.data))throw new Error('復元データの形式が不正です。');
  assertBackupHistoryReadable(payload);
  if(!verifyBackupRoundTrip(payload).passed)throw new Error('保存点を隔離領域で復元できませんでした。');
  return payload;
}

type Pending={vaultId:string;dataHash:string;blob:string};
async function pendingVault(vaultId:string,value?:Pending|null):Promise<Pending|undefined>{
  return new Promise((resolve,reject)=>{const open=indexedDB.open('argus.ownerVault.pending.v1',1);
    open.onupgradeneeded=()=>open.result.createObjectStore('pending',{keyPath:'vaultId'});
    open.onerror=()=>reject(open.error);open.onsuccess=()=>{const db=open.result;const tx=db.transaction('pending',value===undefined?'readonly':'readwrite');const store=tx.objectStore('pending');
      const req=value===undefined?store.get(vaultId):value===null?store.delete(vaultId):store.put(value);let result:Pending|undefined;
      req.onsuccess=()=>{if(value===undefined)result=req.result;};tx.oncomplete=()=>{db.close();resolve(result);};tx.onerror=()=>{db.close();reject(tx.error);};};});
}

export async function ownerVaultProtection():Promise<{current:boolean;exportedAt:string;savedAt:number}|null>{
  try{
    const receipt=readOwnerVaultReceipt();
    if(!receipt)return null;
    const current=await digest(JSON.stringify(buildBackupPayload(false,{deviceId:'protection-check'}).data))===receipt.dataHash;
    return{current,exportedAt:receipt.exportedAt,savedAt:receipt.savedAt};
  }catch{return null;}
}

let saveQueue:Promise<unknown>=Promise.resolve();
export function saveOwnerVault(token:string,pass:string,onProgress:(message:string)=>void,payload=buildBackupPayload(),signal?:AbortSignal):Promise<VaultSnapshot>{
  const work=async()=>{signal?.throwIfAborted();const save=()=>saveOwnerVaultUnlocked(token,pass,onProgress,payload,signal);
    if(typeof navigator!=='undefined'&&navigator.locks)return navigator.locks.request('argus-owner-vault-upload',{signal},save);
    return save();};
  const job=saveQueue.then(work,work);saveQueue=job.catch(()=>{});return job;
}
export async function alreadySavedForVault(pass:string,payload:BackupFile):Promise<boolean>{
  try{const receipt=readOwnerVaultReceipt();return !!receipt
    &&receipt.vaultId===await vaultIdFrom(pass)&&receipt.dataHash===await digest(JSON.stringify(payload.data));}catch{return false;}
}
