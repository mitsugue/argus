import {BACKUP_CONTRACT_VERSION} from './backupMeta';

export const OWNER_VAULT_RECEIPT='argus.ownerVaultReceipt.v1';
export type OwnerVaultReceipt={snapshotId:string;dataHash:string;contractVersion:number;exportedAt:string;savedAt:number;vaultId?:string};

// A receipt describes a previously verified point, not the current device data.
export function readOwnerVaultReceipt():OwnerVaultReceipt|null {
  try{
    const value=JSON.parse(localStorage.getItem(OWNER_VAULT_RECEIPT)||'null');
    if(!value||value.contractVersion!==BACKUP_CONTRACT_VERSION||!/^[a-f0-9]{64}$/.test(value.snapshotId)
      ||!/^[a-f0-9]{64}$/.test(value.dataHash)||!Number.isFinite(value.savedAt)||value.savedAt<=0
      ||!Number.isFinite(new Date(value.savedAt*1000).getTime())
      ||!Number.isFinite(Date.parse(value.exportedAt)))return null;
    return value;
  }catch{return null;}
}
