import { TriangleStepLoader } from '../common/TriangleStepLoader';
import { withoutScreenNotes } from '../../lib/screenNotes';
import React, {useEffect, useState, useSyncExternalStore} from 'react';
import {useMarketBrief} from '../../hooks/useMarketBrief';
import type {AssetItem} from '../../types/assetItem';
import {OwnerAnswerBody, validJob, type Job} from './OwnerDialogue';
import './OwnerOverview.css';
import { hasOwnerSession, subscribeOwner } from '../../lib/ownerSession';
import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../../lib/pollingPolicy';
import { createSavedReadCache } from '../../lib/savedOverviewCache';
const savedReadCache = createSavedReadCache<{ edition?: {key:string;job:Job}; error?:string }>();
subscribeOwner(() => savedReadCache.clear());

const readToken=()=>{try{return localStorage.getItem('argus.ownerSyncToken.v1')||'';}catch{return '';}};
const statusText:Record<string,string>={
  RUNNING:'更新中',
  UNAVAILABLE:'AI応答なし・更新停止',
  REJECTED:'回答を不採用（根拠と不整合）',
  FAILED:'更新失敗',
  INTERRUPTED:'再起動で中断',
  SAVE_FAILED:'保存を確認できず・保存済みの説明',
};
export function OwnerOverview({symbol,market,horizon,asset,onReference}:{symbol:string;market:'JP'|'US';horizon:number;asset?:AssetItem;onReference?:(job:Job|null)=>void}) {
  const session = useSyncExternalStore(subscribeOwner, hasOwnerSession, () => false);
  const {brief,loading:marketLoading,error:marketError}=useMarketBrief();const [token,setToken]=useState(readToken);
  const [edition,setEdition]=useState<{key:string;job:Job}|null>(null);
  const [error,setError]=useState('');const [fetching,setFetching]=useState(false);const [revision,setRevision]=useState(0);
  const base=(import.meta.env.VITE_ARGUS_BACKEND_URL as string|undefined)?.replace(/\/$/,'');
  const contextId=brief?.unifiedContext?.contextId;
  const owner=asset?{symbol,market,state:'WATCHING',
    ...(Number.isFinite(asset.updatedAt)?{reportedAt:new Date(asset.updatedAt).toISOString()}:{}),
  }:undefined;
  const requestKey=JSON.stringify({action:'overview',baseContextId:contextId,symbol,market,horizon,owner});
  const cacheKey = JSON.stringify([token || (session ? 'owner-session' : 'none'), requestKey]);
  useEffect(()=>{setEdition(null);},[token,session]);
  useEffect(()=>{
    const changed=()=>setToken(readToken());
    window.addEventListener('storage',changed);window.addEventListener('argus-owner-connection',changed);
    return()=>{window.removeEventListener('storage',changed);window.removeEventListener('argus-owner-connection',changed);};
  },[]);
  useEffect(()=>{
    if((!token&&!session)||!base){setFetching(false);return;}
    const cached = revision === 0 ? savedReadCache.get(cacheKey) : undefined;
    if(cached?.edition){setEdition(cached.edition);setError('');setFetching(false);return;}
    let stopped=false;let timer:number|undefined;let requestId:string|undefined;
    let active:AbortController|undefined;let pending=false;
    setError('');
    const load=async()=>{
      if(stopped||document.visibilityState!=='visible'||active)return;
      pending=false;const controller=new AbortController();active=controller;setFetching(true);
      const timeout=window.setTimeout(()=>controller.abort(),15000);
      try{
        const response=await fetch(base+'/api/argus/owner-dialogue',{method:'POST',cache:'no-store',signal:controller.signal,
          headers:{'Content-Type':'application/json'},body:JSON.stringify({...JSON.parse(requestKey),ownerToken:token})});
        const value=await response.json();
        if(!response.ok){
          const messages:Record<string,string>={unauthorized:'接続設定を確認してください',dialogue_busy:'順番待ち',dialogue_recovery_pending:'復旧中',market_context_changed:'根拠の更新待ち'};
          if(!stopped){setError(messages[value.error]||'取得できません');
            if(validJob(value.previousOverview)&&value.previousOverview.status==='SUCCEEDED'&&value.previousOverview.context.subject.symbol===symbol&&value.previousOverview.context.subject.market===market&&value.previousOverview.context.horizonSessions===horizon)setEdition({key:'retained:'+requestKey,job:value.previousOverview});
            if(value.error==='dialogue_busy'||value.error==='dialogue_recovery_pending')timer=window.setTimeout(()=>void load(),10000);}
          return;
        }
        const savedOnly=value.overviewRead?.mode==='SAVED_ONLY';
        if(savedOnly&&value.status==='WAITING'){
          if(!stopped){pending=true;const message='AI説明なし';setError(message);savedReadCache.put(cacheKey,{error:message},30_000);timer=window.setTimeout(()=>void load(),30_000);}
          return;
        }
        const evaluation=value.overviewEvaluation;
        const checkedEvaluation=evaluation?.baseMarketContextId===contextId
          &&typeof evaluation.inputsDigest==='string'&&/^[a-f0-9]{64}$/.test(evaluation.inputsDigest)
          &&Number.isFinite(Date.parse(evaluation.checkedAt));
        const reused=value.overviewReuse;
        const checkedReuse=value.status==='SUCCEEDED'&&reused?.baseMarketContextId===contextId
          &&typeof reused.inputsDigest==='string'&&/^[a-f0-9]{64}$/.test(reused.inputsDigest)
          &&Number.isFinite(Date.parse(reused.checkedAt))&&Number.isFinite(Date.parse(reused.originalCompletedAt));
        if(!validJob(value)||value.context.intent!=='SUBJECT_OVERVIEW'||value.context.subject.symbol!==symbol||value.context.subject.market!==market||value.context.horizonSessions!==horizon||(value.context.baseMarketContextId!==contextId&&!checkedReuse&&!checkedEvaluation&&!savedOnly&&value.requestId!==requestId))throw new Error('invalid_overview');
        if(!stopped){const next={key:savedOnly&&value.context.baseMarketContextId!==contextId?'retained:'+requestKey:requestKey,job:value};setEdition(next);setError('');requestId=value.requestId;
          if(value.status==='SUCCEEDED')savedReadCache.put(cacheKey,{edition:next},300_000);
          if(value.status==='RUNNING'){pending=true;timer=window.setTimeout(()=>void load(),3000);}}
      }catch{if(!stopped)setError('接続できません');}
      finally{window.clearTimeout(timeout);active=undefined;if(!stopped)setFetching(false);}
    };
    const stopVisible=subscribeInitialVisibleRead(()=>void load());
    const stopPoll=scheduleVisibleInterval(()=>{if(pending)void load();},30_000);
    if(cached?.error){setError(cached.error);pending=true;}else void load();
    return()=>{stopped=true;active?.abort();stopVisible();stopPoll();if(timer!==undefined)window.clearTimeout(timer);};
  },[requestKey,token,session,cacheKey,base,contextId,revision]);
  const job=edition?.job;
  const current=edition?.key===requestKey&&job?.status==='SUCCEEDED';
  const saved=job?.status==='SUCCEEDED'?job:validJob(job?.previousOverview)&&job.previousOverview.status==='SUCCEEDED'?job.previousOverview:null;
  useEffect(()=>{onReference?.(token||session?saved??null:null);},[saved,token,session,onReference]);
  if(!token&&!session)return <section className="owner-overview"><h3>この銘柄について</h3><p>接続設定が必要（Settings）</p></section>;
  return <section className="owner-overview" aria-label="この銘柄へのARGUSの説明">
    <header><p className="owner-overview__eyebrow">{asset?.displayNameJa||asset?.displayName||(symbol==='N225'?'日経平均':symbol)}</p><span>{horizon}営業日の見通し</span></header>
    {!contextId&&<p role="status">{marketLoading?<TriangleStepLoader label="読み込み中"/>:marketError?"取得できません":"データ待ち"}</p>}
    {error&&<p role="status">{error}</p>}
    {!error&&contextId&&!current&&<p role="status">{fetching||job?.status==='RUNNING'?<TriangleStepLoader label={saved?'更新中':'確認中'}/>:job&&edition?.key===requestKey?statusText[job.status]||'確認中':'更新待ち'}</p>}
    {saved&&<>{!current&&<p className="owner-overview__retained">前回の説明 · {saved.result?.provider?.completedAt||'時刻不明'}</p>}
      {current&&job?.overviewReuse&&<p className="owner-overview__retained">{new Date(job.overviewReuse.originalCompletedAt).toLocaleString('ja-JP')}の説明（根拠に変更なし）</p>}
      <OwnerAnswerBody job={saved} compact/>
      <details><summary>根拠</summary>
        {saved.context.facts.map(f=><p key={f.evidenceId}>{withoutScreenNotes(f.text)}{f.provenance?.url?.startsWith('https://')&&<> <a href={f.provenance.url} target="_blank" rel="noopener noreferrer">出典</a></>}</p>)}
        {saved.persistenceStatus!=='LOCAL_DURABLE'&&<p>保存未確認</p>}
      </details></>}
    {current&&validJob(job?.previousOverview)&&<details><summary>更新前の説明を見る</summary><p>{job.previousOverview.result?.provider?.completedAt||'時刻不明'}</p><OwnerAnswerBody job={job.previousOverview}/></details>}
    {error&&<button type="button" onClick={()=>setRevision(value=>value+1)}>保存した状態を再取得</button>}
  </section>;
}
