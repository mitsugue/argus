import { TriangleStepLoader } from '../common/TriangleStepLoader';
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
  RUNNING:'今の根拠から説明を更新しています。',
  UNAVAILABLE:'AIの応答を取得できず、説明の更新が止まっています。',
  REJECTED:'今回の回答は根拠との整合を確認できませんでした。',
  FAILED:'説明の更新に失敗しました。',
  INTERRUPTED:'再起動で更新が中断しました。重複実行を避けるため、同じ処理は自動再送していません。',
  SAVE_FAILED:'回答の保存を確認できませんでした。保存済みの説明を表示します。',
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
          const messages:Record<string,string>={unauthorized:'所有者の接続設定を確認してください。',dialogue_busy:'別の回答が終わり次第、この銘柄の説明を更新します。',dialogue_recovery_pending:'保存した説明を復旧中です。復旧の確認後に更新します。',market_context_changed:'市場の根拠が更新されました。最新の根拠の取得を待っています。'};
          if(!stopped){setError(messages[value.error]||'銘柄の説明を取得できませんでした。');
            if(validJob(value.previousOverview)&&value.previousOverview.status==='SUCCEEDED'&&value.previousOverview.context.subject.symbol===symbol&&value.previousOverview.context.subject.market===market&&value.previousOverview.context.horizonSessions===horizon)setEdition({key:'retained:'+requestKey,job:value.previousOverview});
            if(value.error==='dialogue_busy'||value.error==='dialogue_recovery_pending')timer=window.setTimeout(()=>void load(),10000);}
          return;
        }
        const savedOnly=value.overviewRead?.mode==='SAVED_ONLY';
        if(savedOnly&&value.status==='WAITING'){
          if(!stopped){pending=true;const message='この銘柄のAI説明はまだ保存されていません。取得済みの決算・価格・ニュースは各項目で読めます。';setError(message);savedReadCache.put(cacheKey,{error:message},30_000);timer=window.setTimeout(()=>void load(),30_000);}
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
      }catch{if(!stopped)setError('接続を確認できませんでした。保存した説明の再取得でAI生成は行いません。');}
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
  if(!token&&!session)return <section className="owner-overview"><h3>この銘柄について</h3><p>所有者の接続設定を保存すると、市場と登録銘柄の情報から説明を自動更新します。</p></section>;
  return <section className="owner-overview" aria-label="この銘柄へのARGUSの説明">
    <header><p className="owner-overview__eyebrow">{asset?.displayNameJa||asset?.displayName||(symbol==='N225'?'日経平均':symbol)}</p><span>{horizon}営業日の見通し</span></header>
    {!contextId&&<p role="status">{marketLoading?<TriangleStepLoader label="市場の根拠を読み込んでいます"/>:marketError?"市場の根拠を取得できません。":"市場の根拠はまだありません。"}</p>}
    {error&&<p role="status">{error}</p>}
    {!error&&contextId&&!current&&<p role="status">{fetching||job?.status==='RUNNING'?<TriangleStepLoader label={saved?'前回の説明を表示しながら更新しています':'この銘柄の説明を確認しています'}/>:job&&edition?.key===requestKey?statusText[job.status]||'説明の更新を確認しています。':'説明の更新待ちです。'}</p>}
    {saved&&<>{!current&&<p className="owner-overview__retained">前回の説明 · {saved.result?.provider?.completedAt||'時刻未確認'}。現在の分析とは区別して表示しています。</p>}
      {current&&job?.overviewReuse&&<details><summary>説明の更新状態</summary><p className="owner-overview__retained">この銘柄・期間の根拠に重要な変更がないため、{new Date(job.overviewReuse.originalCompletedAt).toLocaleString('ja-JP')}の説明を引き続き表示しています。新しいAI解析は行っていません。</p></details>}
      <OwnerAnswerBody job={saved} compact/>
      <details><summary>使った根拠・時点・保存状態</summary>
        {saved.context.facts.map(f=><p key={f.evidenceId}>{f.text}{f.provenance?.url?.startsWith('https://')&&<> <a href={f.provenance.url} target="_blank" rel="noopener noreferrer">出典</a></>}</p>)}
        <p>対象 {market}:{symbol} · {horizon}営業日 · 市場の根拠ID {saved.context.baseMarketContextId}</p>
        <p>応答モデル {saved.result?.provider?.returnedModel||'未確認'} · {saved.result?.provider?.completedAt||'完了時刻未確認'}</p>
        <p>{saved.persistenceStatus==='LOCAL_DURABLE'?'サーバー保存・読み戻し済み':'サーバーへの保存を検証できていません'}。端末変更後の復旧は別途確認が必要です。</p>
      </details></>}
    {current&&validJob(job?.previousOverview)&&<details><summary>更新前の説明を見る</summary><p>{job.previousOverview.result?.provider?.completedAt||'当時の完了時刻は未確認'}</p><OwnerAnswerBody job={job.previousOverview}/></details>}
    {error&&<button type="button" onClick={()=>setRevision(value=>value+1)}>保存した状態を再取得</button>}
  </section>;
}
