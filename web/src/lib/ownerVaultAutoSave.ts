import {buildBackupPayload,hasBackupContent} from './backup';
import {getVaultPass} from './vault';
import {alreadySavedForVault,saveOwnerVault,OWNER_VAULT_RECEIPT} from './ownerVault';

export const AUTO_SAVE_CONFIG='argus.ownerVaultAutoSave.v1';
const OWNER_TOKEN='argus.ownerSyncToken.v1';
export type AutoSaveState={phase:'DISABLED'|'WAITING'|'SAVING'|'SAVED'|'OFFLINE'|'NEEDS_CONNECTION'|'FAILED'|'EMPTY'|'UNSUPPORTED';message:string;checkedAt:number|null;lastSuccessAt:number|null};
let state:AutoSaveState={phase:'DISABLED',message:'自動保存は停止しています。',checkedAt:null,lastSuccessAt:null};
let started=false;let active:AbortController|null=null;let checking=false;let lastAttempt=0;let retryAfter=0;let suspended=false;let failureMessage='';
export function autoSaveEnabled(){try{return !suspended&&JSON.parse(localStorage.getItem(AUTO_SAVE_CONFIG)||'null')?.enabled===true;}catch{return false;}}
export function autoSaveState(){return {...state};}
const notify=(patch:Partial<AutoSaveState>)=>{state={...state,...patch};window.dispatchEvent(new CustomEvent('argus:vault-auto-state'));};
export function disableAutoSave(){
  active?.abort();try{localStorage.setItem(AUTO_SAVE_CONFIG,JSON.stringify({enabled:false}));suspended=false;}
  catch{ suspended=true;notify({phase:'FAILED',message:'この画面の自動保存は停止しましたが、停止設定を保存できません。開き直す前に端末の保存領域を確認してください。'});throw new Error('停止設定を端末へ保存できませんでした。');}
  notify({phase:'DISABLED',message:'自動保存は停止しています。進行済みの遠隔保存点は保持します。'});
  window.dispatchEvent(new CustomEvent('argus:vault-auto-config'));
}
export function enableAutoSave(token:string,pass:string){
  if(!token||!pass)throw new Error('所有者の接続キーとパスフレーズを入力してください。');
  if(!navigator.locks)throw new Error('この環境では自動保存に必要な排他処理を利用できません。手動保存を利用してください。');
  const previous=[OWNER_TOKEN,'argus.vaultPass.v1',AUTO_SAVE_CONFIG].map(key=>[key,localStorage.getItem(key)] as const);
  try{localStorage.setItem(OWNER_TOKEN,token);localStorage.setItem('argus.vaultPass.v1',pass);localStorage.setItem(AUTO_SAVE_CONFIG,JSON.stringify({enabled:true}));}
  catch(error){active?.abort();suspended=true;for(const[key,value]of previous){try{if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}catch{/* Storage failures are reported to the caller. */}}
    try{localStorage.removeItem(AUTO_SAVE_CONFIG);}catch{/* No further save is started by this operation. */}
    throw error;}
  suspended=false;lastAttempt=0;retryAfter=0;window.dispatchEvent(new CustomEvent('argus:vault-auto-config'));void checkAutoSave();
}
export async function checkAutoSave(){
  if(checking)return;checking=true;
  try{
    if(!autoSaveEnabled()){active?.abort();notify({phase:'DISABLED',message:'自動保存は停止しています。'});return;}
    if(document.hidden)return;
    if(!navigator.onLine){notify({phase:'OFFLINE',message:'オフラインです。現在の変更は端末内にあり、接続後に保存を再開します。'});return;}
    if(!navigator.locks){notify({phase:'UNSUPPORTED',message:'この環境では手動保存を利用してください。'});return;}
    let token='';try{token=localStorage.getItem(OWNER_TOKEN)||'';}catch{/* handled below */}
    const pass=getVaultPass()||'';
    if(!token||!pass){notify({phase:'NEEDS_CONNECTION',message:'接続情報を確認できません。自動保存は実行していません。'});return;}
    if(!hasBackupContent()){notify({phase:'EMPTY',message:'保存対象の端末データはまだありません。'});return;}
    const payload=buildBackupPayload();const checkedAt=Date.now();
    if(await alreadySavedForVault(pass,payload)){const receipt=JSON.parse(localStorage.getItem(OWNER_VAULT_RECEIPT)||'null');
      notify({phase:'SAVED',checkedAt,lastSuccessAt:Number.isFinite(receipt?.savedAt)?receipt.savedAt*1000:state.lastSuccessAt,message:'現在のデータは保存照合済みです。'});return;}
    if(Date.now()<retryAfter){notify({phase:'FAILED',checkedAt,message:failureMessage});return;}
    if(Date.now()-lastAttempt<120000){notify({phase:'WAITING',checkedAt,message:'変更をまとめて保存します。完了までは端末内の変更です。'});return;}
    const controller=new AbortController();active=controller;
    await navigator.locks.request('argus-owner-vault-auto',{ifAvailable:true},async lock=>{
      if(!lock)return;
      if(!autoSaveEnabled()||document.hidden||controller.signal.aborted)return;
      // A different tab may have completed the same snapshot while this tab checked it.
      if(await alreadySavedForVault(pass,payload))return;
      if(!autoSaveEnabled()||controller.signal.aborted||token!==localStorage.getItem(OWNER_TOKEN)||pass!==getVaultPass())return;
      lastAttempt=Date.now();notify({phase:'SAVING',checkedAt,message:'変更を暗号化して保存しています。'});
      try{
        const result=await saveOwnerVault(token,pass,message=>{if(!controller.signal.aborted)notify({phase:'SAVING',message});},payload,controller.signal);
        if(controller.signal.aborted||!autoSaveEnabled())return;
        retryAfter=0;notify({phase:await alreadySavedForVault(pass,buildBackupPayload())?'SAVED':'WAITING',lastSuccessAt:result.savedAt*1000,
          message:'保存・読み戻し・復号照合を完了しました。保存中に加わった変更は次回に確認します。'});
      }catch(error){if(controller.signal.aborted||!autoSaveEnabled())return;retryAfter=Date.now()+300000;
        failureMessage=(error instanceof Error?error.message:'自動保存を確認できませんでした。')+' 元の端末データを保持し、後で再試行します。';
        notify({phase:'FAILED',message:failureMessage});}
    });
  }catch(error){if(active?.signal.aborted||!autoSaveEnabled())return;retryAfter=Date.now()+300000;failureMessage=error instanceof Error?error.message:'保存対象を読み取れません。';notify({phase:'FAILED',message:failureMessage});}
  finally{active=null;checking=false;}
}
export function startOwnerVaultAutoSave(){
  if(started)return;started=true;
  const refresh=()=>{if(!autoSaveEnabled())active?.abort();void checkAutoSave();};
  window.addEventListener('argus:vault-auto-config',refresh);window.addEventListener('online',refresh);window.addEventListener('focus',refresh);
  window.addEventListener('storage',event=>{if([OWNER_TOKEN,'argus.vaultPass.v1',AUTO_SAVE_CONFIG].includes(event.key||''))active?.abort();refresh();});
  document.addEventListener('visibilitychange',refresh);
  // Only visible, enabled tabs collect a snapshot. No server/AI work occurs for unchanged content.
  window.setInterval(()=>void checkAutoSave(),15000);void checkAutoSave();
}
