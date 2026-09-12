import React, { useRef, useState, useEffect } from 'react';
import { validMarketBrief, type MarketBrief } from '../../lib/marketBrief';
import { validJapanMarketComparison } from '../../lib/japanMarketComparison';
import { JapanMarketComparisonChart } from '../chart/JapanMarketComparisonChart';

type Entry = { recordId: string; recordedAt: string; sequence: number; sections: NonNullable<MarketBrief['unifiedSummary']>['sections'] };
type Result = { resultId: string; targetDate: string; horizonSessions: number; actualClose: number; forecastValue: number; actualComparisonValue: number; comparisonUnit: string; absoluteErrorPct: number; actualClass: string; receivedAt: string };
type Saved = { recordId: string; recordedAt: string; brief: MarketBrief; calculations: Record<string, { comparison?: unknown }> };
const base = () => String(import.meta.env.VITE_ARGUS_BACKEND_URL ?? '').replace(/\/$/, '');
const stamp = (value: string) => new Date(value).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });

export function MarketAnalysisHistory() {
  const [rows, setRows] = useState<Entry[]>([]), [saved, setSaved] = useState<Saved | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false), [next, setNext] = useState<number | null>(null);
  const [horizon, setHorizon] = useState(5);
  const [outcomes, setOutcomes] = useState<Result[]>([]);
  const flight = useRef<AbortController | null>(null);
  useEffect(() => () => flight.current?.abort(), []);
  const load = async (id?: string, more=false) => {
    if (flight.current) return;
    const controller = new AbortController(); flight.current=controller; setBusy(true);setError(false);
    const timeout=window.setTimeout(()=>controller.abort(),15000);
    try {
      const query=id ? `historyId=${encodeURIComponent(id)}` : `history=1${more&&next?`&beforeSequence=${next}`:''}`;
      const response=await fetch(`${base()}/api/argus/market-brief?${query}`,{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw new Error('history_unavailable');
      const value=await response.json();
      if(id){
        const record=value.record;
        if(value.scope!=='PUBLIC_MARKET'||record?.recordId!==id||!validMarketBrief(record.brief)
          ||!record.calculations||typeof record.calculations!=='object')throw new Error('invalid_history');
        if(!Array.isArray(value.outcomes)||!value.outcomes.every((r:Result)=>r&&typeof r.resultId==='string'
          &&[r.actualClose,r.forecastValue,r.actualComparisonValue,r.absoluteErrorPct].every(Number.isFinite)))throw new Error('invalid_outcomes');
        setSaved(record);setOutcomes(value.outcomes);
      } else {
        if(value.scope!=='PUBLIC_MARKET'||value.actionAuthority!==false||!Array.isArray(value.rows)||value.rows.length>20
          ||!value.rows.every((r:Entry)=>/^[a-f0-9]{64}$/.test(r.recordId)&&Number.isSafeInteger(r.sequence)
            &&Number.isFinite(Date.parse(r.recordedAt))&&typeof r.sections?.view?.textJa==='string'))throw new Error('invalid_history');
        setRows(previous=>more?[...previous,...value.rows]:value.rows);
        setNext(value.hasMore&&Number.isSafeInteger(value.nextBeforeSequence)?value.nextBeforeSequence:null);setLoaded(true);
      }
    } catch { setError(true); }
    finally {window.clearTimeout(timeout);flight.current=null;setBusy(false);}
  };
  const comparison=saved?.calculations?.[String(horizon)]?.comparison;
  return <details className="at-analysis-history" onToggle={event=>{if(event.currentTarget.open&&!loaded&&!busy)void load();}}>
    <summary>前回の見立て・保存した予測を見る</summary>
    <p>発表した時点の根拠と計算結果です。後の入力で過去の線を書き換えません。</p>
    {busy&&<p role="status">履歴を読み込んでいます。</p>}
    {error&&<p role="status">履歴を取得できませんでした。<button type="button" onClick={()=>void load()}>再取得</button></p>}
    {loaded&&!rows.length&&<p>保存済みの見立てはまだありません。</p>}
    {rows.map(row=><p key={row.recordId}><button type="button" disabled={busy} onClick={()=>void load(row.recordId)}>
      {stamp(row.recordedAt)} · {row.sections.view.textJa}</button></p>)}
    {next&&<button type="button" disabled={busy} onClick={()=>void load(undefined,true)}>さらに前を見る</button>}
    {saved&&<section aria-label="保存した見立て">
      <h4>{stamp(saved.recordedAt)}の見立て</h4>
      <p>{saved.brief.unifiedSummary?.sections.view.textJa}</p>
      <p>変更理由：{saved.brief.unifiedSummary?.sections.changes.textJa}</p>
      <p>見方を変える条件：{saved.brief.unifiedSummary?.sections.invalidation.textJa}</p>
      <label>保存した予測の期間 <select value={horizon} onChange={e=>setHorizon(Number(e.target.value))}>
        {[1,5,10,20].map(value=><option key={value} value={value}>{value}営業日</option>)}</select></label>
      {validJapanMarketComparison(comparison,horizon)?<JapanMarketComparisonChart document={comparison}/>
        :<p>この時点・期間の計算結果は未取得です。</p>}
      <details><summary>当時の根拠とモデル</summary>
        {saved.brief.facts.map((fact,index)=><p key={index}>{fact.text}</p>)}
        <p>要求 {saved.brief.aiDiagnostics?.requestedModel??'未確認'} ／ 応答 {saved.brief.aiDiagnostics?.returnedModel??'未確認'}</p>
      </details>
      <h4>その後の結果</h4>
      {!outcomes.length&&<p>対象営業日の終値との照合待ちです。取得できていない結果は補完しません。</p>}
      {outcomes.map(row=><p key={row.resultId}>{row.horizonSessions}営業日 · {row.targetDate}終値 {row.actualClose.toLocaleString('ja-JP')}円
        ／ 当時の計算 {row.forecastValue.toLocaleString('ja-JP',{maximumFractionDigits:2})}{row.comparisonUnit==='ANCHOR_100'?'（基準100）':'円'}
        ／ 同じ尺度の実績 {row.actualComparisonValue.toLocaleString('ja-JP',{maximumFractionDigits:2})}
        ／ 誤差 {row.absoluteErrorPct.toFixed(2)}%<br/>取得 {stamp(row.receivedAt)}</p>)}
      <p>訂正後の結果も追記します。単発の結果で計算ルールは変えません。これは予測確率の検証ではありません。</p>
    </section>}
  </details>;
}
