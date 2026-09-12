import React from 'react';
import { MarketAnalysisHistory } from './MarketAnalysisHistory';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import './ArgusToday.css';

// v13.5.36 MARKET SITUATION BRIEF (owner 2026-08-26): NOW/WHY/NEXT — the
// deterministic composer selects verified facts; AI only compresses them
// (numbers/probabilities can never be invented — server-side validator).
export const MarketBriefCard: React.FC<{ signals?: { activeCount: number; total: number } | null;
  cutoff?: string | null; market?: string }> = ({ signals, cutoff, market }) => {
  const { brief, error, loading, retry } = useMarketBrief();
  // v13.5.62 (GPT review item 4): the brief's 成立x/7 chip is rendered from the
  // SAME market-view document as the MARKET SIGNALS header, stamped with its
  // information cutoff, so the two never show different counts.
  const cutoffJa = cutoff ? new Date(cutoff).toLocaleTimeString('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit' }) : null;
  const chartChip = signals ? `成立 ${signals.activeCount}/${signals.total}${cutoffJa ? `（${cutoffJa} 時点）` : ''}`
    : market === 'US' ? '米国: 7条件は適用外（類似局面のみ）' : brief?.chips.chart;
  const updateState = error ? <p role="status" className="at-brief__update">
    {brief ? '見立てを更新できません。最後に取得した説明を表示しています。' : '見立てを取得できません。'}
    {brief && <small> 要約作成 {new Date(brief.generatedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}</small>}
    <button type="button" onClick={retry} disabled={loading}>再読込</button>
  </p> : null;
  if (!brief) return <div className="at-brief" aria-label="ARGUSの今日の見立て">
    {updateState ?? <p role="status">見立てを確認中です。</p>}</div>;
  const unified = brief.unifiedSummary;
  const hasSixSections = unified && ['view', 'reasons', 'changes', 'impact', 'next', 'invalidation'].every(key => {
    const row = unified.sections?.[key as keyof typeof unified.sections];
    return row && typeof row.textJa === 'string' && ['FACT', 'INFERENCE', 'UNKNOWN'].includes(row.kind)
      && Array.isArray(row.evidenceIds);
  });
  if (hasSixSections && unified?.schemaVersion === 'argus-unified-brief-v1'
    && unified.actionAuthority === false && unified.contextId === brief.unifiedContext?.contextId) {
    const labels = { view: '今の見立て', reasons: '重要な理由', changes: '前回からの変化',
      impact: '自分への影響', next: '次に確認すること', invalidation: '見方を変える条件' } as const;
    const kinds = { FACT: '確認した事実', INFERENCE: '見立て・推論', UNKNOWN: '未確認' };
    return <div className="at-brief at-unified-brief" aria-label="ARGUSの今日の見立て" data-argus-contract="unified-brief-v1">
      <small>ARGUSの今日の見立て · {brief.aiDiagnostics?.completedAt
        ? new Date(brief.aiDiagnostics.completedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }) : '生成時刻を確認中'}</small>
      {updateState}
      <p className="at-unified-brief__view">{unified.sections.view.textJa}</p>
      <div className="at-brief__rows">{(Object.keys(labels) as Array<keyof typeof labels>).filter(key => key !== 'view').map(key =>
        <div key={key}><b>{labels[key]}</b><span>{unified.sections[key].textJa}
          <small className="at-unified-brief__kind">{kinds[unified.sections[key].kind]}</small></span></div>)}</div>
      <details><summary>根拠と説明の状態を見る</summary>
        <p>要求モデル {brief.aiDiagnostics?.requestedModel ?? '未確認'} · 応答モデル {brief.aiDiagnostics?.returnedModel ?? '未確認'}</p>
        <p>{brief.analysisHistory?.status === 'LOCAL_DURABLE'
          ? 'この見立てと当時の計算結果をサーバーの永続領域へ保存しました。遠隔バックアップからの復旧確認は未完了です。'
          : 'この見立ての永続保存は未完了です。画面に表示できても保存成功とは限りません。'}</p>
        {(Object.keys(labels) as Array<keyof typeof labels>).map(key => <div key={key}>
          <b>{labels[key]}の根拠</b>
          {unified.sections[key].evidenceIds.length === 0 ? <p>根拠未取得</p> : unified.sections[key].evidenceIds.map(id => {
            const current = Array.isArray(brief.unifiedContext?.facts) ? brief.unifiedContext.facts : [];
            const prior = Array.isArray(brief.unifiedContext?.previousFacts) ? brief.unifiedContext.previousFacts : [];
            const fact = current.find(row => row.evidenceId === id) ?? prior.find(row => row.evidenceId === id);
            return <div key={id} className="at-brief-source"><p>{fact?.text ?? '参照元を確認できません'}</p>
              <small>{fact?.provenance?.sourceLabel ?? fact?.source ?? '出典未確認'}
                {fact?.provenance?.eventId ? ` · 記録 ${fact.provenance.eventId}` : ''}
                {fact?.provenance?.revision != null ? ` · 改訂 ${fact.provenance.revision}` : ''}</small>
              <small>公表 {fact?.provenance?.publishedAt ?? '未確認'} · 受信 {fact?.provenance?.receivedAt ?? '未確認'}
                {fact?.provenance?.observedAt ? ` · 観測 ${fact.provenance.observedAt}` : ''}</small>
              {fact?.provenance?.url && <a href={fact.provenance.url} target="_blank" rel="noopener noreferrer">出典を開く</a>}
            </div>;
          })}
        </div>)}
      </details>
      <MarketAnalysisHistory />
    </div>;
  }
  const now = brief.aiText?.nowJa ?? brief.now;
  const why = brief.aiText?.whyJa ?? brief.why;
  const next = brief.aiText?.nextJa ?? brief.next;
  return <div className="at-brief" data-argus-contract="market-brief-v1"
    aria-label="今の市場（売買権限なし）">
    {updateState}
    {brief.unifiedStatus && brief.unifiedStatus !== 'GENERATED' && <p role="status">
      {brief.generationWorker?.status === 'RUNNING' ? '統合AIが見立てを更新しています。'
        : ['FAILED', 'INVALID_RESPONSE', 'UNAVAILABLE'].includes(brief.generationWorker?.status ?? '')
          ? '統合AIの更新を完了できませんでした。次の定期処理で再試行します。'
          : '統合AIの説明は更新待ちです。'}取得済み情報の要約を表示しています。
      {brief.lastSuccessfulAiAt && <small> 最終成功 {brief.lastSuccessfulAiAt}</small>}
    </p>}
    <small>今の市場 — 取得済み情報の要約{brief.aiText ? '（AI圧縮・参考）' : ''}</small>
    <div className="at-brief__rows">
      <div><b>今</b><span>{now}</span></div>
      <div><b>理由</b><span>{why}</span></div>
      <div><b>次に確認</b><span>{next}</span></div>
    </div>
    <div className="at-brief__chips">
      <span>チャート <b>{chartChip}</b></span>
      <span>ニュース <b>{brief.chips.news}</b></span>
      <span>次イベント <b>{brief.chips.nextEvent}</b></span>
      <span>主リスク <b>{brief.chips.mainRisk}</b></span>
    </div>
  </div>;
};

