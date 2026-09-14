import React, {useEffect, useState} from 'react';
import {useMarketBrief} from '../../hooks/useMarketBrief';
import type {AssetItem} from '../../types/assetItem';
import {OwnerAnswerBody, validJob, type Job} from './OwnerDialogue';
import './OwnerOverview.css';

const readToken=()=>{try{return localStorage.getItem('argus.ownerSyncToken.v1')||'';}catch{return '';}};
const statusText:Record<string,string>={
  RUNNING:'今の根拠から説明を更新しています。',
  UNAVAILABLE:'AIの応答を取得できず、説明の更新が止まっています。',
  REJECTED:'今回の回答は根拠との整合を確認できませんでした。',
  FAILED:'説明の更新に失敗しました。',
  INTERRUPTED:'再起動で更新が中断しました。重複実行を避けるため、同じ処理は自動再送していません。',
  SAVE_FAILED:'回答の保存を確認できませんでした。保存済みの説明を表示します。',
};
export function OwnerOverview({symbol,market,horizon,asset,onReference}:{symbol:string;market:'JP'|'US';horizon:number;asset?:AssetItem;onReference:(job:Job|null)=>void}) {
  const {brief}=useMarketBrief();const [token,setToken]=useState(readToken);
  const [edition,setEdition]=useState<{key:string;job:Job}|null>(null);
  const [error,setError]=useState('');const [revision,setRevision]=useState(0);
  const base=(import.meta.env.VITE_ARGUS_BACKEND_URL as string|undefined)?.replace(/\/$/,'');
  const contextId=brief?.unifiedContext?.contextId;
  const owner=asset?{symbol,market,state:(asset.quantity??0)>0?'HELD':'WATCHING',
    ...((asset.quantity??0)>0?{quantity:asset.quantity,averageCost:asset.avgCost}:{}),
    ...(asset.purchaseReason?.trim()?{purchaseReason:asset.purchaseReason.trim()}:{}),
    ...(asset.holdingPeriod?.trim()?{holdingPeriod:asset.holdingPeriod.trim()}:{}),
    ...(Number.isFinite(asset.updatedAt)?{reportedAt:new Date(asset.updatedAt).toISOString()}:{}),
  }:undefined;
  const requestKey=JSON.stringify({action:'overview',baseContextId:contextId,symbol,market,horizon,owner});
  useEffect(()=>{setEdition(null);},[token]);
  useEffect(()=>{
    const changed=()=>setToken(readToken());
    window.addEventListener('storage',changed);window.addEventListener('argus-owner-connection',changed);
    return()=>{window.removeEventListener('storage',changed);window.removeEventListener('argus-owner-connection',changed);};
  },[]);
  useEffect(()=>{
    if(!token||!contextId||!base)return;
    let stopped=false;let timer:number|undefined;let requestId:string|undefined;
    let active:AbortController|undefined;
    setError('');
    const load=async()=>{
      const controller=new AbortController();active=controller;
      const timeout=window.setTimeout(()=>controller.abort(),15000);
      try{
        const response=await fetch(base+'/api/argus/owner-dialogue',{method:'POST',cache:'no-store',signal:controller.signal,
          headers:{'Content-Type':'application/json'},body:JSON.stringify({...(!requestId?JSON.parse(requestKey):{action:'status',requestId}),ownerToken:token})});
        const value=await response.json();
        if(!response.ok){
          const messages:Record<string,string>={unauthorized:'所有者の接続設定を確認してください。',dialogue_busy:'別の回答が終わり次第、この銘柄の説明を更新します。',dialogue_recovery_pending:'保存した説明を復旧中です。復旧の確認後に更新します。',market_context_changed:'市場の根拠が更新されました。最新の根拠の取得を待っています。'};
          if(!stopped){setError(messages[value.error]||'銘柄の説明を取得できませんでした。');
            if(validJob(value.previousOverview)&&value.previousOverview.status==='SUCCEEDED'&&value.previousOverview.context.subject.symbol===symbol&&value.previousOverview.context.subject.market===market&&value.previousOverview.context.horizonSessions===horizon)setEdition({key:'retained:'+requestKey,job:value.previousOverview});
            if(value.error==='dialogue_busy'||value.error==='dialogue_recovery_pending')timer=window.setTimeout(()=>void load(),10000);}
          return;
        }
        if(!validJob(value)||value.context.intent!=='SUBJECT_OVERVIEW'||value.context.subject.symbol!==symbol||value.context.subject.market!==market||value.context.horizonSessions!==horizon||value.context.baseMarketContextId!==contextId)throw new Error('invalid_overview');
        if(!stopped){setEdition({key:requestKey,job:value});setError('');requestId=value.requestId;
          if(value.status==='RUNNING')timer=window.setTimeout(()=>void load(),3000);}
      }catch{if(!stopped)setError('接続を確認できませんでした。再取得でも同じ生成IDを使います。');}
      finally{window.clearTimeout(timeout);}
    };
    void load();
    return()=>{stopped=true;active?.abort();if(timer!==undefined)window.clearTimeout(timer);};
  },[requestKey,token,base,contextId,revision]);
  const job=edition?.job;
  const current=edition?.key===requestKey&&job?.status==='SUCCEEDED';
  const saved=job?.status==='SUCCEEDED'?job:validJob(job?.previousOverview)&&job.previousOverview.status==='SUCCEEDED'?job.previousOverview:null;
  useEffect(()=>{onReference(token?saved??null:null);},[saved,token,onReference]);
  if(!token)return <section className="owner-overview"><h3>この銘柄について</h3><p>所有者の接続設定を保存すると、市場と登録した保有情報から説明を自動更新します。</p></section>;
  return <section className="owner-overview" aria-label="この銘柄へのARGUSの説明">
    <header><p className="owner-overview__eyebrow">{asset?.displayNameJa||asset?.displayName||(symbol==='N225'?'日経平均':symbol)}</p><span>{horizon}営業日の見通し</span></header>
    {!contextId&&<p role="status">市場の根拠を取得しています。</p>}
    {error&&<p role="status">{error}</p>}
    {!error&&contextId&&!current&&<p role="status">{job&&edition?.key===requestKey?statusText[job.status]||'説明の更新を確認しています。':'今の根拠から説明を更新しています。'}</p>}
    {saved&&<>{!current&&<p className="owner-overview__retained">前回の説明 · {saved.result?.provider?.completedAt||'時刻未確認'}。現在の分析とは区別して表示しています。</p>}
      <OwnerAnswerBody job={saved}/>
      <details><summary>使った根拠・時点・保存状態</summary>
        {saved.context.facts.map(f=><p key={f.evidenceId}>{f.text}{f.provenance?.url?.startsWith('https://')&&<> <a href={f.provenance.url} target="_blank" rel="noopener noreferrer">出典</a></>}</p>)}
        <p>対象 {market}:{symbol} · {horizon}営業日 · 市場の根拠ID {saved.context.baseMarketContextId}</p>
        <p>応答モデル {saved.result?.provider?.returnedModel||'未確認'} · {saved.result?.provider?.completedAt||'完了時刻未確認'}</p>
        <p>{saved.persistenceStatus==='LOCAL_DURABLE'?'サーバー保存・読み戻し済み':'保存確認待ち'}。端末変更後の復旧は別途確認が必要です。</p>
      </details></>}
    {current&&validJob(job?.previousOverview)&&<details><summary>更新前の説明を見る</summary><p>{job.previousOverview.result?.provider?.completedAt||'当時の完了時刻は未確認'}</p><OwnerAnswerBody job={job.previousOverview}/></details>}
    {error&&<button type="button" onClick={()=>setRevision(value=>value+1)}>保存した状態を再取得</button>}
  </section>;
}
