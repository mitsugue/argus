import React, {useEffect, useRef, useState} from 'react';
import {useMarketBrief} from '../../hooks/useMarketBrief';
import type {AssetItem} from '../../types/assetItem';
import './OwnerDialogue.css';

type Section={textJa:string;kind:string;evidenceIds:string[]};
type Job={requestId:string;status:string;persistenceStatus:string;remoteRecoveryVerified:boolean;
  context:{question:string;subject:{symbol:string;market:string};horizonSessions:number;baseMarketContextId:string;
    facts:Array<{evidenceId:string;text:string}>;calculatedHypothesis?:{status:string;value?:number;unit?:string;noteJa?:string;comparisonPoints?:Array<{usdJpy:number;value:number}>}};
  result?:{answer?:{sections:Record<string,Section>};provider?:{returnedModel?:string;completedAt?:string}}};
const labels:Record<string,string>={view:'今の見立て',reasons:'重要な理由',changes:'前回からの変化',impact:'自分への影響',next:'次に確認すること',invalidation:'見方を変える条件'};
const states:Record<string,string>={RUNNING:'AIが根拠を確認しています。履歴は引き続き読めます。',INTERRUPTED:'再起動で処理が中断しました。課金の重複を避けるため、自動再実行はしていません。',REJECTED:'回答の根拠と表現を検証できなかったため、表示を保留しました。',UNAVAILABLE:'AIが応答を返せませんでした。取得済みの市場情報は利用できます。',FAILED:'回答処理に失敗しました。',SAVE_FAILED:'回答の保存に失敗しました。この端末表示だけでは復元を保証できません。'};
const errors:Record<string,string>={unauthorized:'所有者の接続キーを確認してください。',owner_sync_unconfigured:'サーバーの所有者認証が未設定です。',durable_storage_unavailable:'履歴の保存先が利用できないため、質問を送信できません。',market_context_changed:'市場の根拠が更新されました。更新後に新しい質問として送信してください。',dialogue_busy:'別の質問に回答中です。履歴から進行状況を確認できます。',dialogue_input_invalid:'入力した対象・期間・仮定を確認してください。'};
const readKey=()=>{try{return localStorage.getItem('argus.ownerSyncToken.v1')||'';}catch{return '';}};
const validJob=(x:any):x is Job=>!!x&&typeof x.requestId==='string'&&typeof x.status==='string'&&x.context?.subject&&Array.isArray(x.context?.facts)
  &&typeof x.context?.question==='string'&&(!x.result?.answer||Object.keys(labels).every(k=>typeof x.result.answer.sections?.[k]?.textJa==='string'));

export function OwnerDialogue({symbol,market,horizon,asset}:{symbol:string;market:'JP'|'US';horizon:number;asset?:AssetItem}) {
  const {brief,retry}=useMarketBrief(); const [token,setToken]=useState(readKey);
  const [connectionOpen,setConnectionOpen]=useState(()=>!readKey());
  const [question,setQuestion]=useState('');const [reason,setReason]=useState('');const [period,setPeriod]=useState('');
  const [fx,setFx]=useState('');const [job,setJob]=useState<Job|null>(null);const [rows,setRows]=useState<Job[]>([]);
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [nextBefore,setNextBefore]=useState<number|null>(null);
  const pending=useRef<Record<string,unknown>|null>(null);const alive=useRef(true);
  const base=(import.meta.env.VITE_ARGUS_BACKEND_URL as string|undefined)?.replace(/\/$/,'');
  const scope=`${market}:${symbol}:${horizon}`;const scopeRef=useRef(scope);scopeRef.current=scope;
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const previousScope=useRef(scope);
  useEffect(()=>{if(previousScope.current===scope)return;previousScope.current=scope;setJob(null);setRows([]);setError('');setQuestion('');setFx('');pending.current=null;setNextBefore(null);},[scope]);
  const post=async (payload:Record<string,unknown>)=>{
    const controller=new AbortController();const timer=window.setTimeout(()=>controller.abort(),15000);
    try {
      if(!base)throw new Error('接続先が未設定です。');
      const response=await fetch(base+'/api/argus/owner-dialogue',{method:'POST',cache:'no-store',signal:controller.signal,
        headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,ownerToken:token})});
      const data=await response.json();if(!response.ok)throw new Error(errors[data.error]||'処理を完了できませんでした。');return data;
    } finally {window.clearTimeout(timer);}
  };
  useEffect(()=>{
    if(job?.status!=='RUNNING')return;
    let stopped=false;let flight=false;
    const timer=window.setInterval(async()=>{
      if(flight||document.visibilityState!=='visible')return;flight=true;
      try{const data=await post({action:'status',requestId:job.requestId});if(!stopped&&validJob(data))setJob(data);}
      catch{if(!stopped)setError('進行状況の更新に失敗しました。再送は同じ質問IDを使用します。');}
      finally{flight=false;}
    },3000);
    return()=>{stopped=true;window.clearInterval(timer);};
  },[job?.requestId,job?.status,token]);
  const ask=async()=>{
    if(busy)return;setBusy(true);setError('');const startScope=scope;
    try{
      if(!pending.current){
        const owner=asset?{symbol,market,state:(asset.quantity??0)>0?'HELD':'WATCHING',
          ...((asset.quantity??0)>0?{quantity:asset.quantity,averageCost:asset.avgCost}:{}),
          ...(reason.trim()?{purchaseReason:reason.trim()}:{}),...(period.trim()?{holdingPeriod:period.trim()}:{}),reportedAt:new Date().toISOString()}:undefined;
        pending.current={action:'ask',requestId:crypto.randomUUID(),baseContextId:brief?.unifiedContext?.contextId,
          symbol,market,horizon,question:question.trim(),owner,
          ...(job?{previousRequestId:job.requestId}:{}),
          ...(fx?{hypothesis:{kind:'FX_TRANSLATION',usdJpy:Number(fx),yenIndexUnchanged:true}}:{})};
      }
      const data=await post(pending.current);
      if(!validJob(data))throw new Error('回答形式を確認できませんでした。');
      if(alive.current&&scopeRef.current===startScope){setJob(data);pending.current=null;}
    }catch(e){if(alive.current&&scopeRef.current===startScope)setError(e instanceof Error?e.message:'接続できませんでした。');}
    finally{if(alive.current)setBusy(false);}
  };
  const history=async(more=false)=>{
    const startScope=scope;setError('');
    try{const data=await post({action:'history',...(more&&nextBefore?{before:nextBefore}:{})});
      if(!Array.isArray(data.items)||!data.items.every(validJob))throw new Error('履歴形式を確認できませんでした。');
      if(alive.current&&scopeRef.current===startScope){setRows(old=>more?[...old,...data.items]:data.items);setNextBefore(data.nextBefore);}}
    catch(e){setError(e instanceof Error?e.message:'履歴を取得できませんでした。');}
  };
  const reset=()=>{setJob(null);setFx('');pending.current=null;setError('');};
  const answer=job?.result?.answer;const matching=rows.filter(r=>r.context.subject.symbol===symbol&&r.context.subject.market===market&&r.context.horizonSessions===horizon);
  return <section className="owner-dialogue" aria-label="ARGUSに質問する">
    <h3>この見立てについて話す</h3><p>{market==='JP'&&symbol==='N225'?'日経平均':symbol} · {horizon}営業日。表示中の市場の根拠と、登録した保有情報から説明します。</p>
    <details open={connectionOpen} onToggle={e=>setConnectionOpen(e.currentTarget.open)}><summary>所有者の接続設定</summary>
      <label>接続キー<input aria-label="所有者の接続キー" type="password" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)}/></label>
      <button type="button" onClick={()=>{try{localStorage.setItem('argus.ownerSyncToken.v1',token);setConnectionOpen(false);}catch{setError('接続キーを保存できませんでした。');}}}>この端末に保存</button></details>
    {asset&&<details><summary>今回の回答に使う保有情報</summary><p>{(asset.quantity??0)>0?`保有数量 ${asset.quantity}・平均取得単価 ${asset.avgCost??'未登録'}`:'監視中・保有数量は未登録'}。質問時に所有者専用の履歴とAIへ送信します。</p>
      <label>購入理由<input value={reason} maxLength={1000} onChange={e=>{pending.current=null;setReason(e.target.value);}}/></label>
      <label>保有期間<input value={period} maxLength={160} onChange={e=>{pending.current=null;setPeriod(e.target.value);}}/></label></details>}
    <div className="owner-dialogue__suggestions">{['前回から何が変わった？','この状況なら、何を待てばいい？','短期と中期で見方は違う？'].map(q=><button key={q} type="button" onClick={()=>{setQuestion(q);pending.current=null;}}>{q}</button>)}</div>
    <label>ARGUSへの質問<textarea maxLength={1000} value={question} placeholder="あなたの気になること" onChange={e=>{setQuestion(e.target.value);pending.current=null;}}/></label>
    {market==='JP'&&symbol==='N225'&&<details><summary>為替の仮定を試す</summary><p>日経平均の円建て価格を変えずにドル換算します。円高による株価予測とは異なります。</p>
      <label>仮定するドル円<input type="number" min="0.01" step="0.01" value={fx} onChange={e=>{setFx(e.target.value);pending.current=null;}}/></label></details>}
    <div className="owner-dialogue__actions"><button type="button" disabled={busy||job?.status==='RUNNING'||!token||!question.trim()||!brief?.unifiedContext} onClick={()=>void ask()}>{busy?'送信中…':pending.current?'同じ質問IDで再送':'ARGUSに質問する'}</button>
      <button type="button" disabled={!token} onClick={()=>void history()}>保存した会話</button><button type="button" onClick={reset}>仮定を閉じて元の見立てへ</button></div>
    {error&&<p role="alert">{error} <button type="button" onClick={()=>{retry();pending.current=null;}}>市場の根拠を更新</button></p>}
    {job&&<article aria-live="polite"><h4>{job.context.question}</h4><p>{job.context.horizonSessions}営業日 · {job.context.subject.symbol}</p>
      {states[job.status]&&<p role="status">{states[job.status]}</p>}
      {job.status==='SAVE_FAILED'&&<button type="button" onClick={()=>void post({action:'save',requestId:job.requestId}).then(data=>{if(validJob(data))setJob(data);}).catch(()=>setError('保存を再試行できませんでした。'))}>AIを再実行せず保存を再試行</button>}
      {answer&&Object.entries(labels).map(([key,label])=><div key={key}><strong>{label}</strong><p>{answer.sections[key].textJa}</p><small>{({FACT:'確認済みの事実',INFERENCE:'推論',UNKNOWN:'未確認'} as Record<string,string>)[answer.sections[key].kind]}</small></div>)}
      {job.context.calculatedHypothesis&&<p>{job.context.calculatedHypothesis.status==='AVAILABLE'?`仮定の計算: ${job.context.calculatedHypothesis.value?.toLocaleString()} ${job.context.calculatedHypothesis.unit}。${job.context.calculatedHypothesis.noteJa}`:'この仮定の数値計算に必要な原典は未取得です。'}</p>}
      <HypothesisChart points={job.context.calculatedHypothesis?.comparisonPoints}/>
      <details><summary>使った根拠と保存状態</summary>{job.context.facts.map(f=><p key={f.evidenceId}>{f.text}</p>)}<p>市場の根拠ID: {job.context.baseMarketContextId}</p><p>応答モデル: {job.result?.provider?.returnedModel||'未確認'} · {job.result?.provider?.completedAt||'完了時刻未確認'}</p>
        <p>{job.persistenceStatus==='LOCAL_DURABLE'?'サーバー保存・読み戻し済み':'保存確認待ち'}。別環境からの復旧確認は未完了です。</p></details></article>}
    {matching.length>0&&<div className="owner-dialogue__history">{matching.map(row=><button type="button" key={row.requestId} onClick={()=>setJob(row)}>{row.context.question} · {row.context.horizonSessions}営業日</button>)}</div>}
    {nextBefore&&<button type="button" onClick={()=>void history(true)}>以前の会話を読む</button>}
  </section>;
}


function HypothesisChart({points}:{points?:Array<{usdJpy:number;value:number}>}) {
  if(!points||points.length!==3||!points.every(p=>Number.isFinite(p.usdJpy)&&Number.isFinite(p.value)&&p.value>0))return null;
  const values=points.map(p=>p.value),low=Math.min(...values),high=Math.max(...values);
  if(high===low)return null;
  const y=(v:number)=>150-(v-low)/(high-low)*105;
  return <figure className="owner-dialogue__chart"><figcaption>仮定したドル円とドル換算値（時間軸ではありません）</figcaption>
    <svg viewBox="0 0 420 210" role="img" aria-label="円建て日経平均を一定と仮定したドル換算の比較">
      <polyline fill="none" stroke="#97cee4" strokeDasharray="6 5" strokeWidth="2" points={points.map((p,i)=>`${55+i*150},${y(p.value)}`).join(' ')}/>
      {points.map((p,i)=><g key={i}><circle cx={55+i*150} cy={y(p.value)} r={i===1?5:3} fill="#97cee4"/><text x={55+i*150} y={y(p.value)-13} textAnchor="middle" fill="#dce5eb" fontSize="13">{p.value.toFixed(2)} USD</text><text x={55+i*150} y="185" textAnchor="middle" fill="#a8b9c6" fontSize="13">{p.usdJpy.toFixed(2)} 円/ドル</text></g>)}
    </svg><p>中央が入力した仮定です。左右はその前後の換算例で、将来経路や実測の為替ではありません。</p>
  </figure>;
}
