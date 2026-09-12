import React, { useEffect, useRef, useState } from 'react';
import { validUsageView, usageCost, usageCount, type UsageView, type UsageGroup } from '../../lib/aiUsageView';
import './AiUsagePanel.css';

const labels: Record<string, string> = {
  owner_dialogue: '対話・銘柄への影響', market_brief: '市場の見立て', news_analysis: 'ニュースの影響解析',
  headline_translation: '見出しの翻訳', ai_judgment: '判断の補助', ai_double_check: '補助照合',
  osint_research: '公開情報の調査', provider_ping: 'AI接続の確認', benchmark_evaluation: '比較検証',
  research_benchmark: '調査手法の検証', macro_event_analysis: 'イベントの前後分析',
};
const monthNow = () => new Date().toISOString().slice(0, 7);
const localTime = (value?: string | null) => value ? new Date(value).toLocaleString('ja-JP', {timeZone:'Asia/Tokyo'}) + ' JST' : '未記録';
const initialToken = () => { try { return localStorage.getItem('argus.ownerSyncToken.v1') || ''; } catch { return ''; } };
const tokens = (value:number, unknown:number, records:number) => {
  const formatted = usageCount(value,unknown,records);
  return formatted === '未取得' ? formatted : formatted + 'トークン';
};

function Group({ row }: { row: UsageGroup }) {
  return <article className="ai-usage__group">
    <div className="ai-usage__row"><h4>{labels[row.feature] || 'その他の解析'}</h4><strong>{usageCost(row)}</strong></div>
    <p>{row.provider} · 応答モデル {row.returnedModel || '未取得'}</p>
    <p>呼出し {usageCount(row.providerCalls, row.unknownProviderCallCount, row.records)}回 · 応答成功 {row.outcomes.success || 0}件</p>
    <details><summary>使用量と記録の範囲</summary>
      <p>機能：{row.feature} · 要求モデル：{row.requestedModel || '未取得'}</p>
      <p>入力 {tokens(row.inputTokens,row.unknownTokenRecords.inputTokens || 0,row.records)}</p>
      <p>出力 {tokens(row.outputTokens,row.unknownTokenRecords.outputTokens || 0,row.records)}</p>
      <p>入力のうちキャッシュ {tokens(row.cachedInputTokens,row.unknownTokenRecords.cachedInputTokens || 0,row.records)}</p>
      <p>記録された処理時間の合計 {(row.knownDurationMs/1000).toLocaleString('ja-JP')}秒{row.unknownDurationRecords ? `（${row.unknownDurationRecords}件は不明）` : ''}</p>
      <p>明示された再試行 {row.retryRecords}件 · 試行番号が不明 {row.unknownAttemptRecords}件</p>
      <p>応答エラー {row.outcomes.provider_error || 0}件。応答成功は、説明の採用・保存成功を意味しません。</p>
    </details>
  </article>;
}

export function AiUsagePanel() {
  const [token,setToken] = useState(initialToken); const [month,setMonth] = useState(monthNow);
  const [connectionOpen,setConnectionOpen] = useState(()=>!token);
  const [view,setView] = useState<UsageView|null>(null); const [error,setError] = useState('');
  const [busy,setBusy] = useState(false); const requestId = useRef(0);
  const controller = useRef<AbortController|null>(null);
  useEffect(() => () => { requestId.current++; controller.current?.abort(); }, []);
  const load = async (more=false) => {
    const id = ++requestId.current; controller.current?.abort(); const abort = new AbortController(); controller.current=abort;
    const timer = window.setTimeout(()=>abort.abort(),15000); setBusy(true);setError('');
    try {
      const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string|undefined)?.replace(/\/$/,'');
      if(!base) throw new Error('接続先を確認できません。');
      const response = await fetch(base+'/api/argus/owner-dialogue',{method:'POST',cache:'no-store',signal:abort.signal,
        headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'usage',ownerToken:token,month,
          ...(more && view ? {offset:view.nextOffset,throughSequence:view.throughSequence} : {})})});
      if(response.status===401||response.status===403)throw new Error('所有者の接続キーを確認してください。');
      if(response.status===409)throw new Error('新しい記録が追加されました。「内訳を更新」で読み直してください。');
      if(!response.ok)throw new Error('利用量の記録を取得できませんでした。');
      const data:unknown = await response.json();
      if(!validUsageView(data,month))throw new Error('記録の形式を確認できませんでした。');
      if(requestId.current===id)setView(old=>({...data,rows:more&&old?[...old.rows,...data.rows]:data.rows}));
    }catch(e){if(requestId.current===id)setError(e instanceof Error?e.message:'利用量を取得できませんでした。');}
    finally{window.clearTimeout(timer);if(requestId.current===id)setBusy(false);}
  };
  const change = (next:()=>void) => {requestId.current++;controller.current?.abort();setBusy(false);setView(null);setError('');next();};
  return <section className="card ai-usage" aria-label="機能別AI使用量">
    <h3>機能別のAI利用量</h3><p>対話と同じ所有者接続で、保存済みの内訳を確認できます。この操作でAIは実行しません。</p>
    <details open={connectionOpen} onToggle={e=>setConnectionOpen(e.currentTarget.open)}><summary>所有者の接続設定</summary>
      <label>接続キー<input type="password" autoComplete="off" value={token} onChange={e=>change(()=>setToken(e.target.value))}/></label>
      <p>入力したキーはこの欄から端末へ保存しません。</p>
    </details>
    <div className="ai-usage__controls"><label>集計月（UTC）<input type="month" value={month} max={monthNow()}
      onChange={e=>change(()=>setMonth(e.target.value))}/></label>
      <button type="button" disabled={busy||!token||!month} onClick={()=>void load()}>内訳を更新</button></div>
    {busy&&<p role="status">保存された記録を確認しています。</p>}
    {error&&<p role="alert">{error}{view?' 前回取得した内訳を表示しています。':''}</p>}
    {view&&<>
      <p>内訳の取得：{localTime(view.generatedAt)}</p>
      {view.status==='AVAILABLE'&&view.totals ? <>
        <div className="ai-usage__row"><span>記録された参考費用</span><strong>{usageCost(view.totals)}</strong></div>
        <p>{view.monthUtc}（UTC）の記録 {view.totals.records.toLocaleString('ja-JP')}件 · 呼出し {usageCount(view.totals.providerCalls,view.totals.unknownProviderCallCount,view.totals.records)}回</p>
        {!view.rows.length&&<p>この月の保存済み記録はありません。実際の利用がなかったことの証明ではありません。</p>}
        {view.rows.map((r,i)=><Group key={`${r.feature}:${r.provider}:${r.requestedModel}:${r.returnedModel}:${i}`} row={r}/>)}
        {view.nextOffset!==null&&<button type="button" disabled={busy} onClick={()=>void load(true)}>続きの内訳を表示</button>}
        <p>呼出し開始の記録範囲：{localTime(view.firstRecordedAt)}〜{localTime(view.lastRecordedAt)}</p>
      </> : <p>利用量の保存記録を確認できていません。0円・未使用という意味ではありません。</p>}
      {view.state.pendingReceipts!==null&&view.state.pendingReceipts>0&&<p>保存待ち {view.state.pendingReceipts}件は、この内訳に含まれていません。</p>}
      {!view.remoteRecoveryVerified&&<p>遠隔バックアップからの復旧は未確認です。</p>}
    </>}
    <details><summary>費用と回数の意味</summary>
      <p>通常トークン単価による参考推定です。キャッシュ割引・検索ツール等の料金を含む確定請求額ではありません。既存の費用総額には加算しません。</p>
      <p>回数はSDK呼出しの記録です。SDK内部の再試行、アプリのキャッシュ利用、記録開始前や中断中の未保存分は再構成していません。</p>
      <p>UTCの日付で集計します。応答成功と、説明の検証・採用・履歴保存は別の状態です。</p>
    </details>
  </section>;
}
