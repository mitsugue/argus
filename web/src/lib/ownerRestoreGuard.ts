import {hasBackupContent} from './backup';
import {OWNER_VAULT_RECEIPT,ownerVaultProtection,saveOwnerVault} from './ownerVault';
import {AUTO_SAVE_CONFIG,disableAutoSave} from './ownerVaultAutoSave';
import {getVaultPass} from './vault';

export function usesOwnerSnapshots():boolean {
  try{return localStorage.getItem(AUTO_SAVE_CONFIG)!==null||localStorage.getItem(OWNER_VAULT_RECEIPT)!==null;}
  catch{return true;}
}

// Legacy import tools may change the same keys as the new snapshot workflow.
// Stop new uploads and preserve current edits before any caller applies a restore.
export async function preserveBeforeOwnerRestore(progress:(message:string)=>void):Promise<boolean>{
  if(!usesOwnerSnapshots())return false;
  disableAutoSave();
  if(!hasBackupContent())return true;
  if((await ownerVaultProtection())?.current)return true;
  const token=localStorage.getItem('argus.ownerSyncToken.v1')||'';const pass=getVaultPass()||'';
  if(!token||!pass)throw new Error('現在の変更を先に「端末データを暗号化して保存」で保存・照合してください。復元はまだ行っていません。');
  progress('復元前に現在の変更を別の暗号化保存点へ退避しています。');
  await saveOwnerVault(token,pass,progress);
  // An edit made while uploading must not be overwritten by the selected import.
  if(!(await ownerVaultProtection())?.current)throw new Error('退避中にデータが変わりました。現在の変更を保存してから復元をやり直してください。');
  return true;
}
