import { TriangleStepLoader } from '../common/TriangleStepLoader';
import React, {useEffect, useRef, useState} from 'react';
import {useMarketBrief} from '../../hooks/useMarketBrief';
import type {AssetItem} from '../../types/assetItem';
import type {MarketBrief} from '../../lib/marketBrief';
import type {JapanMarketComparison} from '../../types/japanMarketComparison';
import {validJapanMarketComparison} from '../../lib/japanMarketComparison';
import {JapanMarketComparisonChart} from '../chart/JapanMarketComparisonChart';
import './OwnerDialogue.css';
import '../today/ArgusEditorialSurface.css';

type Section={textJa:string;kind:string;evidenceIds:string[]};
export type Job={remoteBackup?:{status?:string;lastVerifiedAt?:string;pending?:boolean};requestId:string;status:string;persistenceStatus:string;remoteRecoveryVerified:boolean;
  overviewReuse?:{checkedAt:string;baseMarketContextId:string;inputsDigest:string;originalCompletedAt:string};
  previousOverview?:Job|null;context:{referenceEdition?:{recordId:string;recordedAt:string;isCurrentMarketAnalysis:false};intent?:string;eventFocus?:{eventId:string;snapshot?:{relatedMemory?:{policyVersion?:string;records?:Array<{outcomeWindows?:Array<{status:string}>}>}}};contextId:string;question:string;subject:{symbol:string;market:string};horizonSessions:number;baseMarketContextId:string;
    facts:Array<{evidenceId:string;text:string;provenance?:{url?:string;sourceLabel?:string}}>;
    retrievalRecord?:{policyVersion:string;scope:string;archiveSearchStatus:string;counterevidenceSearchStatus:string;selection:{mandatoryCurrent:string[];previousDistinct:string[];previousSharedWithCurrent:string[]}};
    indexComparison?:JapanMarketComparison;indexComparisonEvidenceId?:string;
    calculatedHypothesis?:{status:string;value?:number;unit?:string;noteJa?:string;baselinePressurePoints?:number;comparisonPoints?:Array<{usdJpy:number;value:number}>}};
  result?:{answer?:{sections:Record<string,Section>;presentationStatus?:string;presentationPlan?:MarketBrief['presentationPlan']};provider?:{returnedModel?:string;completedAt?:string}}};
const labels:Record<string,string>={view:'今の見立て',reasons:'重要な理由',changes:'前回からの変化',impact:'自分への影響',next:'次に確認すること',invalidation:'見方を変える条件'};
const states:Record<string,string>={RUNNING:'AIが根拠を確認しています。履歴は引き続き読めます。',INTERRUPTED:'再起動で処理が中断しました。課金の重複を避けるため、自動再実行はしていません。',REJECTED:'回答の根拠と表現を検証できなかったため、表示を保留しました。',UNAVAILABLE:'AIが応答を返せませんでした。取得済みの市場情報は利用できます。',FAILED:'回答処理に失敗しました。',SAVE_FAILED:'回答の保存に失敗しました。この端末表示だけでは復元を保証できません。'};
const errors:Record<string,string>={saved_market_reference_unavailable:'表示していた説明の保存データを復旧中です。復旧後に同じ質問を再送できます。',unauthorized:'所有者の接続キーを確認してください。',owner_sync_unconfigured:'サーバーの所有者認証が未設定です。',durable_storage_unavailable:'履歴の保存先が利用できないため、質問を送信できません。',market_context_changed:'市場の根拠が更新されました。更新後に新しい質問として送信してください。',dialogue_recovery_pending:'保存した会話を復旧中、または遠隔保存の接続を確認できていません。二重実行を防ぐため、復旧確認後に質問できます。',dialogue_busy:'別の質問に回答中です。履歴から進行状況を確認できます。',dialogue_input_invalid:'入力した対象・期間・仮定を確認してください。'};
const readKey=()=>{try{return localStorage.getItem('argus.ownerSyncToken.v1')||'';}catch{return '';}};
export const validJob=(x:any):x is Job=>!!x&&typeof x.requestId==='string'&&typeof x.status==='string'&&x.context?.subject&&Array.isArray(x.context?.facts)
  &&typeof x.context?.question==='string'&&(!x.result?.answer||Object.keys(labels).every(k=>typeof x.result.answer.sections?.[k]?.textJa==='string'));

function dialogueChoices(job: Job | null) {
  const answer=job?.result?.answer;const plan=answer?.presentationPlan;
  const hasChart=job?.context.subject.symbol==='N225'&&job.context.subject.market==='JP'
    &&validJapanMarketComparison(job.context.indexComparison,job.context.horizonSessions);
  const expected=hasChart?[...Object.keys(labels),'nikkei-comparison']:Object.keys(labels);
  if(answer?.presentationStatus==='GENERATED'&&plan?.schemaVersion==='argus-presentation-intent-v1'
    &&plan.actionAuthority===false&&plan.surface==='dialogue'&&plan.contextId===job?.context.contextId
    &&plan.subject===job?.context.subject.symbol&&plan.horizonSessions===job?.context.horizonSessions
    &&Array.isArray(plan.elements)&&plan.elements.length===expected.length&&new Set(plan.elements.map(row=>row?.id)).size===expected.length
    &&plan.elements.filter(row=>row?.emphasis==='primary').length===1
    &&plan.elements.every(row=>row&&expected.includes(row.id)&&['lead','support','detail'].includes(row.placement)
      &&['primary','normal','quiet'].includes(row.emphasis)&&!(['view','impact','invalidation','nikkei-comparison'].includes(row.id)&&row.placement==='detail')))
    return plan.elements;
  return Object.keys(labels).map(id=>({id,placement:'support',emphasis:'normal',purposeJa:''}));
}

export function OwnerDialogue({symbol,market,horizon,asset,baseContextId,previousRequestId,initialQuestion,focusEventId,referenceRecordId}:{symbol:string;market:'JP'|'US';horizon:number;asset?:AssetItem;baseContextId?:string;previousRequestId?:string;initialQuestion?:string;focusEventId?:string;referenceRecordId?:string}) {
  const {brief,retry}=useMarketBrief(); const [token,setToken]=useState(readKey);
  const [connectionOpen,setConnectionOpen]=useState(false);
  const [question,setQuestion]=useState(initialQuestion??'');const [reason,setReason]=useState<string|null>(null);const [period,setPeriod]=useState<string|null>(null);
  const [fx,setFx]=useState('');const [fiscalGrowth,setFiscalGrowth]=useState('');
  const [fiscalRate,setFiscalRate]=useState('');const [job,setJob]=useState<Job|null>(null);const [rows,setRows]=useState<Job[]>([]);
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [historyLoading,setHistoryLoading]=useState(false);const [nextBefore,setNextBefore]=useState<number|null>(null);
  const pending=useRef<Record<string,unknown>|null>(null);const alive=useRef(true);
  const base=(import.meta.env.VITE_ARGUS_BACKEND_URL as string|undefined)?.replace(/\/$/,'');
  const scope=`${market}:${symbol}:${horizon}:${focusEventId??''}:${referenceRecordId??''}`;const scopeRef=useRef(scope);scopeRef.current=scope;
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const previousScope=useRef(scope);
  useEffect(()=>{if(previousScope.current===scope)return;previousScope.current=scope;setJob(null);setRows([]);setError('');setQuestion(initialQuestion??'');setReason(null);setPeriod(null);setFx('');setFiscalGrowth('');setFiscalRate('');pending.current=null;setNextBefore(null);},[scope]);
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
  const ownerReason=reason??asset?.purchaseReason??'';const ownerPeriod=period??asset?.holdingPeriod??'';
  const ask=async()=>{
    if(busy)return;setBusy(true);setError('');const startScope=scope;
    try{
      if(!pending.current){
        const owner=asset?{symbol,market,state:(asset.quantity??0)>0?'HELD':'WATCHING',
          ...((asset.quantity??0)>0?{quantity:asset.quantity,averageCost:asset.avgCost}:{}),
          ...(ownerReason.trim()?{purchaseReason:ownerReason.trim()}:{}),...(ownerPeriod.trim()?{holdingPeriod:ownerPeriod.trim()}:{}),reportedAt:new Date().toISOString()}:undefined;
        pending.current={action:'ask',requestId:crypto.randomUUID(),baseContextId:baseContextId ?? brief?.unifiedContext?.contextId,
          symbol,market,horizon,question:question.trim(),owner,
          ...(focusEventId?{focusEventId}:{}),
          ...(referenceRecordId?{referenceRecordId}:{}),
          ...(job||previousRequestId?{previousRequestId:job?.requestId??previousRequestId}:{}),
          ...(fiscalGrowth||fiscalRate?{hypothesis:{kind:'FISCAL_ASSUMPTION',
            ...(fiscalGrowth?{growthPct:Number(fiscalGrowth)}:{}),
            ...(fiscalRate?{effectiveRatePct:Number(fiscalRate)}:{})}}:
            fx?{hypothesis:{kind:'FX_TRANSLATION',usdJpy:Number(fx),yenIndexUnchanged:true}}:{})};
      }
      const data=await post(pending.current);
      if(!validJob(data))throw new Error('回答形式を確認できませんでした。');
      if(alive.current&&scopeRef.current===startScope){setJob(data);pending.current=null;}
    }catch(e){if(alive.current&&scopeRef.current===startScope)setError(e instanceof Error?e.message:'接続できませんでした。');}
    finally{if(alive.current)setBusy(false);}
  };
  const history=async(more=false)=>{
    if(historyLoading)return;setHistoryLoading(true);const startScope=scope;setError('');
    try{const data=await post({action:'history',...(more&&nextBefore?{before:nextBefore}:{})});
      if(!Array.isArray(data.items)||!data.items.every(validJob))throw new Error('履歴形式を確認できませんでした。');
      if(alive.current&&scopeRef.current===startScope){setRows(old=>more?[...old,...data.items]:data.items);setNextBefore(data.nextBefore);}}
    catch(e){if(alive.current)setError(e instanceof Error?e.message:'履歴を取得できませんでした。');}
    finally{if(alive.current)setHistoryLoading(false);}
  };
  const reset=()=>{setJob(null);setFx('');setFiscalGrowth('');setFiscalRate('');pending.current=null;setError('');};
  const answer=job?.result?.answer;const matching=rows.filter(r=>r.context.subject.symbol===symbol&&r.context.subject.market===market&&r.context.horizonSessions===horizon&&(r.context.eventFocus?.eventId??null)===(focusEventId??null));
  const connected=Boolean(token.trim());
  const contextReady=Boolean(baseContextId ?? brief?.unifiedContext?.contextId);
  const canAsk=connected&&contextReady&&Boolean(question.trim())&&!busy&&job?.status!=='RUNNING';
  return <section className="owner-dialogue" aria-label="ARGUSに質問する">
    <div className="owner-dialogue__intro"><div><h3>{focusEventId?'このイベントについて話す':'この見立てについて話す'}</h3>
      <p>{market==='JP'&&symbol==='N225'?'日経平均':symbol} · {horizon}営業日。表示中の根拠を保ったまま、ARGUSに続けて質問できます。</p></div>
      <span className={connected?'is-connected':'is-disconnected'}>{connected?'接続済み':'接続が必要'}</span></div>
    <details className="owner-dialogue__connection" open={connectionOpen||!connected} onToggle={e=>setConnectionOpen(e.currentTarget.open)}><summary>{connected?'接続設定を確認':'質問機能を接続する'}</summary>
      <label>接続キー<input aria-label="所有者の接続キー" type="password" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)}/></label>
      <button type="button" onClick={()=>{try{localStorage.setItem('argus.ownerSyncToken.v1',token);window.dispatchEvent(new Event('argus-owner-connection'));setConnectionOpen(false);}catch{setError('接続キーを保存できませんでした。');}}}>この端末に保存</button></details>
    {asset&&<details><summary>今回の回答に使う保有情報</summary><p>{(asset.quantity??0)>0?`保有数量 ${asset.quantity}・平均取得単価 ${asset.avgCost??'未登録'}`:'監視中・保有数量は未登録'}。質問時に所有者専用の履歴とAIへ送信します。ここでの変更は今回の会話だけに使い、登録した保有情報は変更しません。</p>
      <label>購入理由<input value={ownerReason} maxLength={1000} onChange={e=>{pending.current=null;setReason(e.target.value);}}/></label>
      <label>保有期間<input value={ownerPeriod} maxLength={160} onChange={e=>{pending.current=null;setPeriod(e.target.value);}}/></label></details>}
    <div className="owner-dialogue__suggestions" aria-label="質問候補">{(focusEventId?['事前の予想と結果はどう違う？','市場は実際にどう反応した？','次に何を確認すればいい？']:['前回から何が変わった？','この状況なら、何を待てばいい？','短期と中期で見方は違う？']).map(q=><button key={q} type="button" onClick={()=>{setQuestion(q);pending.current=null;}}>{q}</button>)}</div>
    <div className="owner-dialogue__composer"><label>質問を入力<textarea maxLength={1000} value={question} placeholder="例：円高が続いたら、この見立てはどう変わる？" onChange={e=>{setQuestion(e.target.value);pending.current=null;}}/></label>
      <div className="owner-dialogue__send"><small>{!connected?'この端末の接続キーを保存すると質問できます。':!contextReady?'見立ての根拠を読み込み中です。':'表示中の根拠と同じ対象・期間で回答します。'}</small>
        <button type="button" className="owner-dialogue__primary" disabled={!canAsk} onClick={()=>void ask()}>{busy?<TriangleStepLoader compact label="送信中"/>:pending.current?'同じ質問IDで再送':'質問する'}</button></div></div>
    {market==='JP'&&symbol==='N225'&&<details><summary>為替の仮定を試す</summary><p>日経平均の円建て価格を変えずにドル換算します。円高による株価予測とは異なります。</p>
      <label>仮定するドル円<input type="number" min="0.01" step="0.01" value={fx} onChange={e=>{setFx(e.target.value);setFiscalGrowth('');setFiscalRate('');pending.current=null;}}/></label></details>}
    {market==='JP'&&Boolean(brief?.unifiedContext?.fiscalEnvironment)&&<details><summary>財政環境の仮定を試す</summary>
      <p>現在の公表値を基準に、名目成長率か政府の実効金利を変えた場合の機械的な債務比率の圧力を計算します。市場の10年国債利回りや日本株の価格予測ではありません。</p>
      <label>仮定する日本の名目GDP成長率（%）<input type="number" step="0.1" value={fiscalGrowth} onChange={e=>{setFiscalGrowth(e.target.value);setFx('');pending.current=null;}}/></label>
      <label>仮定する政府の実効金利（%）<input type="number" step="0.1" value={fiscalRate} onChange={e=>{setFiscalRate(e.target.value);setFx('');pending.current=null;}}/></label></details>}
    <div className="owner-dialogue__actions"><button type="button" disabled={!connected||historyLoading} onClick={()=>void history()}>保存した会話を見る</button>
      {(job||fx||fiscalGrowth||fiscalRate)&&<button type="button" onClick={reset}>元の見立てへ戻す</button>}</div>
    {error&&<p role="alert">{error} <button type="button" onClick={()=>{retry();pending.current=null;}}>市場の根拠を更新</button></p>}
    {job&&<article aria-live="polite"><h4>{job.context.question}</h4><p>{job.context.horizonSessions}営業日 · {job.context.subject.symbol}</p>
      {states[job.status]&&<p role="status">{job.status==='RUNNING'?<TriangleStepLoader label={states[job.status]}/>:states[job.status]}</p>}
      {job.status==='SAVE_FAILED'&&<button type="button" onClick={()=>void post({action:'save',requestId:job.requestId}).then(data=>{if(validJob(data))setJob(data);}).catch(()=>setError('保存を再試行できませんでした。'))}>AIを再実行せず保存を再試行</button>}
      {answer&&<OwnerAnswerBody job={job}/>}
      {job.context.calculatedHypothesis&&<p>{job.context.calculatedHypothesis.status==='AVAILABLE'?`仮定の計算: ${job.context.calculatedHypothesis.baselinePressurePoints!=null?`もとの圧力 ${job.context.calculatedHypothesis.baselinePressurePoints.toLocaleString()} ポイント → `:''}${job.context.calculatedHypothesis.value?.toLocaleString()} ${job.context.calculatedHypothesis.unit}。${job.context.calculatedHypothesis.noteJa}`:'この仮定の数値計算に必要な原典は未取得です。'}</p>}
      <HypothesisChart points={job.context.calculatedHypothesis?.comparisonPoints}/>
      <details><summary>使った根拠と保存状態</summary>{job.context.facts.map(f=><p key={f.evidenceId}>{f.text}
        {f.provenance?.url?.startsWith('https://')&&<> <a href={f.provenance.url} target="_blank" rel="noopener noreferrer">{f.provenance.sourceLabel||'出典'}を確認</a></>}
      </p>)}<p>市場の根拠ID: {job.context.baseMarketContextId}</p><p>応答モデル: {job.result?.provider?.returnedModel||'未確認'} · {job.result?.provider?.completedAt||'完了時刻未確認'}</p>
        {job.remoteBackup&&<p>暗号化した遠隔コピー: {job.remoteBackup.status==='VERIFIED'?'保存・読み戻し済み':job.remoteBackup.status==='RUNNING'?'保存確認中':'未確認'}{job.remoteBackup.lastVerifiedAt?` · ${job.remoteBackup.lastVerifiedAt}`:''}{job.remoteBackup.pending?' · 最新変更の保存待ち':''}</p>}
        <p>{job.persistenceStatus==='LOCAL_DURABLE'?'サーバー保存・読み戻し済み':'保存確認待ち'}。別環境からの復旧確認は未完了です。</p></details></article>}
    {historyLoading&&<p><TriangleStepLoader label="保存した会話を読み込んでいます"/></p>}
    {matching.length>0&&<div className="owner-dialogue__history">{matching.map(row=><button type="button" key={row.requestId} onClick={()=>setJob(row)}>{row.context.question} · {row.context.horizonSessions}営業日</button>)}</div>}
    {nextBefore&&<button type="button" disabled={historyLoading} onClick={()=>void history(true)}>以前の会話を読む</button>}
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

export function OwnerAnswerBody({job}:{job:Job}) {
  const answer=job.result?.answer;
  if(!answer)return null;
  return <div className="argus-editorial owner-dialogue__answer">
    {job.context.referenceEdition&&<p className="argus-editorial__retained">保存した説明（{new Date(job.context.referenceEdition.recordedAt).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'})}）の根拠への回答です。最新の市場分析とは区別しています。</p>}
    {dialogueChoices(job).map(choice=>{
        if(choice.id==='nikkei-comparison')return <section className={`argus-editorial__element is-${choice.emphasis} placement-${choice.placement}`} key={choice.id}>
          <JapanMarketComparisonChart document={job.context.indexComparison!}/>
          <p className="argus-editorial__uncertain">この回答を作成した時点の比較です。現在の値で過去の線を書き換えていません。</p>
        </section>;
        const content=<><p className="argus-editorial__text">{answer.sections[choice.id].textJa}</p>
          {answer.sections[choice.id].kind==='UNKNOWN'&&<small>確認できていない範囲</small>}</>;
        const className=`argus-editorial__element is-${choice.emphasis} placement-${choice.placement} element-${choice.id}`;
        return choice.placement==='detail'?<details className={className} key={choice.id}><summary>{labels[choice.id]}</summary>{content}</details>
          :<section className={className} key={choice.id}><h2>{labels[choice.id]}</h2>{content}</section>;
      })}
    {job.context.retrievalRecord?.policyVersion==='owner-edition-retrieval-v1'&&<details className="argus-editorial__element is-quiet placement-detail">
      <summary>この回答で確認した範囲</summary>
      <p className="argus-editorial__text">この対象・期間の現在の根拠と、比較できる前回の根拠を読みました。内容が変わらない資料は一度だけ読み、変更・相違・不明点は残しています。</p>
      <p className="argus-editorial__uncertain">{job.context.retrievalRecord.archiveSearchStatus==='BOUNDED_EVENT_MEMORY'
        ?'同じテーマの保存済みイベントから、当時の根拠と反対材料を件数・容量の範囲内で確認しました。過去の仮説に対する反証であり、現在の見方を直接否定するものではありません。全履歴を網羅した検索ではありません。'
        :job.context.retrievalRecord.archiveSearchStatus==='UNAVAILABLE'
          ?'関連する過去記録を確認できなかったため、現在と前回の根拠で説明しています。'
          :'過去の全記録を検索する機能はまだ接続していません。'}見つからなかったことは、反証が存在しないことを意味しません。</p>
      {job.context.eventFocus?.snapshot?.relatedMemory?.policyVersion==='bounded-event-history-v2'&&<p className="argus-editorial__uncertain">
        {job.context.eventFocus.snapshot.relatedMemory.records?.some(record=>record.outcomeWindows?.some(window=>window.status==='OBSERVED'))
          ?'過去の仮説に結び付いた、その後の実測結果も参照しました。当時の予測と現在の見通しは分け、結果不足を的中扱いにしていません。'
          :'後日の実測結果は、この回答の検索範囲では確認できていません。過去の仮説が当たったという根拠には使っていません。'}
      </p>}
    </details>}
    </div>;
}
