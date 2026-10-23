import { CreditConditionsDetails } from './CreditConditionsDetails';
import { NumericalResearchDetails } from './NumericalResearchDetails';
import { FiscalEnvironmentDetails } from './FiscalEnvironmentDetails';
import { TriangleStepLoader } from '../common/TriangleStepLoader';
import React from 'react';
import { MarketAnalysisHistory } from './MarketAnalysisHistory';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import './ArgusToday.css';
import { editorialEdition, readableBriefEdition } from '../../lib/presentationIntent';
import type { MarketBrief } from '../../lib/marketBrief';
import { ArgusEditorialSurface } from './ArgusEditorialSurface';
import { TodayDecisionStrip, type CriticalTodayNews } from './TodayDecisionStrip';
import { marketChanges, marketWording } from '../../lib/marketWording';
import { withoutScreenNotes } from '../../lib/screenNotes';

// v13.5.36 MARKET SITUATION BRIEF (owner 2026-08-26): NOW/WHY/NEXT — the
// deterministic composer selects verified facts; AI only compresses them
// (numbers/probabilities can never be invented — server-side validator).
/** Owner wording for a gated regeneration: the reason and when it resumes. */
export function gateNoteJa(brief: MarketBrief): string | null {
  const gate = brief.generationGate;
  if (!gate?.reason || !gate.reasonJa) return null;
  const resumes = gate.resumesAt ? new Date(gate.resumesAt) : null;
  const when = resumes && !Number.isNaN(resumes.getTime())
    ? `${resumes.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' })}に自動再開` : null;
  const budget = gate.monthlyBudgetUsd != null && gate.monthSpentUsd != null && /monthly/.test(gate.reason)
    ? `（今月 $${gate.monthSpentUsd.toFixed(2)} / 上限 $${gate.monthlyBudgetUsd.toFixed(2)}）`
    : gate.dailyBudgetUsd != null && gate.daySpentUsd != null && /daily/.test(gate.reason)
      ? `（本日 $${gate.daySpentUsd.toFixed(2)} / 上限 $${gate.dailyBudgetUsd.toFixed(2)}）` : '';
  return `${gate.reasonJa}${budget}。${when ? `${when}。` : ''}`;
}

/** Absence of a generated edition does not prove that its worker stopped. */
export function briefWaitingTitle(brief: MarketBrief): string {
  if (brief.generationWorker?.status === 'RUNNING') return '見立てを作成中';
  if (['FAILED', 'INVALID_RESPONSE', 'UNAVAILABLE'].includes(brief.generationWorker?.status ?? '')
    || ['FAILED', 'INVALID_RESPONSE', 'UNAVAILABLE'].includes(brief.unifiedStatus ?? '')) {
    return '見立てを作成できませんでした';
  }
  return '見立て待ち';
}

export function retainedBriefNote(brief: MarketBrief | null, requestFailed: boolean): string {
  if (requestFailed) return '更新確認待ち・保存版';
  if (brief?.generationWorker?.status === 'RUNNING') return '作成中・保存版';
  if (['FAILED', 'INVALID_RESPONSE', 'UNAVAILABLE'].includes(brief?.generationWorker?.status ?? '')
    || ['FAILED', 'INVALID_RESPONSE', 'UNAVAILABLE'].includes(brief?.unifiedStatus ?? '')) return '更新失敗・保存版';
  return '保存版';
}

export const MarketBriefCard: React.FC<{ signals?: { activeCount: number; total: number } | null;
  cutoff?: string | null; market?: string; editorial?: boolean; criticalNews?: CriticalTodayNews[] }> = ({ signals, cutoff, market, editorial = false, criticalNews }) => {
  const { brief: responseBrief, error, loading, retry } = useMarketBrief();
  const brief = readableBriefEdition(responseBrief) ?? responseBrief;
  const retained = brief !== responseBrief;
  // v13.5.62 (GPT review item 4): the brief's 成立x/7 chip is rendered from the
  // SAME market-view document as the MARKET SIGNALS header, stamped with its
  // information cutoff, so the two never show different counts.
  const cutoffJa = cutoff ? new Date(cutoff).toLocaleTimeString('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit' }) : null;
  const chartChip = signals ? `6サイン 成立 ${signals.activeCount} / ${signals.total}${cutoffJa ? `（${cutoffJa}）` : ''}`
    : market === 'US' ? '米国: 6サインは適用外' : brief?.chips.chart;
  const updateState = brief ? (loading || error || retained ? <span role="status" className="at-brief__update">
    {loading ? (retained ? retainedBriefNote(responseBrief, false) : '確認中') : retainedBriefNote(responseBrief, Boolean(error))}
    {error && <button type="button" onClick={retry} disabled={loading} aria-label="見立てを再確認">↻</button>}
  </span> : null) : loading ? <p className="at-brief__update"><TriangleStepLoader label="読み込み中" /></p>
    : error ? <p role="status" className="at-brief__update">取得できません <button type="button" onClick={retry}>再読込</button></p> : null;
  if (!brief) return <div className="at-brief" aria-label="ARGUSの今日の見立て">
    {updateState ?? <p role="status">見立てなし</p>}<CreditConditionsDetails /><MarketAnalysisHistory key="saved-history" /></div>;
  const edition = editorial ? editorialEdition(brief) : null;
  const gateNote = gateNoteJa(responseBrief ?? brief);
  if (edition) return <ArgusEditorialSurface brief={edition} updateState={updateState} retained={edition !== brief}
    generationStatus={responseBrief?.generationWorker?.status} retainedNote={gateNote} criticalNews={criticalNews} />;
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
    return <div className={`at-brief at-unified-brief${editorial ? ' at-brief--current' : ''}`} data-layout={editorial ? 'current-four-cards' : 'reference'} aria-label="ARGUSの今日の見立て" data-argus-contract="unified-brief-v1">
      <header className="at-brief__edition"><span>MARKET VIEW</span><time dateTime={brief.aiDiagnostics?.completedAt ?? brief.generatedAt}>
        {new Date(brief.aiDiagnostics?.completedAt ?? brief.generatedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} 更新</time>{updateState}</header>
      {editorial ? <TodayDecisionStrip brief={brief} criticalNews={criticalNews} />
        : <p className="at-unified-brief__view">{unified.sections.view.textJa}</p>}
      <div className="at-brief__rows">{(Object.keys(labels) as Array<keyof typeof labels>).filter(key => editorial ? ['reasons', 'changes', 'invalidation'].includes(key) : key !== 'view').map(key =>
        <div key={key} data-brief-section={key}><b>{labels[key]}</b><span>{editorial ? (key === 'changes' ? marketChanges(unified.sections[key].textJa) : marketWording(unified.sections[key].textJa)) : unified.sections[key].textJa}
          {!editorial && <small className="at-unified-brief__kind">{kinds[unified.sections[key].kind]}</small>}</span></div>)}</div>
      <details><summary>根拠</summary>
        <p>見立ての作成日時 {new Date(brief.aiDiagnostics?.completedAt ?? brief.generatedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}</p>
        {(Object.keys(labels) as Array<keyof typeof labels>).map(key => <div key={key}>
          <b>{labels[key]}の根拠</b>
          {editorial && <p>{unified.sections[key].textJa}<small className="at-unified-brief__kind">{kinds[unified.sections[key].kind]}</small></p>}
          {unified.sections[key].evidenceIds.length === 0 ? <p>根拠なし</p> : unified.sections[key].evidenceIds.map(id => {
            const current = Array.isArray(brief.unifiedContext?.facts) ? brief.unifiedContext.facts : [];
            const prior = Array.isArray(brief.unifiedContext?.previousFacts) ? brief.unifiedContext.previousFacts : [];
            const fact = current.find(row => row.evidenceId === id) ?? prior.find(row => row.evidenceId === id);
            return <div key={id} className="at-brief-source"><p>{fact?.text ? withoutScreenNotes(fact.text) : '参照元なし'}</p>
              <small>{fact?.provenance?.sourceLabel ?? fact?.source ?? '出典不明'}
                {(fact?.provenance?.observedAt ?? fact?.provenance?.publishedAt ?? fact?.provenance?.receivedAt)
                  ? ` · ${(fact?.provenance?.observedAt ?? fact?.provenance?.publishedAt ?? fact?.provenance?.receivedAt ?? '').slice(0, 10)}` : ''}</small>
              {fact?.provenance?.url && <a href={fact.provenance.url} target="_blank" rel="noopener noreferrer">出典を開く</a>}
            </div>;
          })}
        </div>)}
        {editorial && <><NumericalResearchDetails brief={brief} /><FiscalEnvironmentDetails brief={brief} /><CreditConditionsDetails brief={brief} /><MarketAnalysisHistory key="saved-history" /></>}
      </details>
      {!editorial && <><NumericalResearchDetails brief={brief} /><FiscalEnvironmentDetails brief={brief} /><CreditConditionsDetails brief={brief} /><MarketAnalysisHistory key="saved-history" /></>}
    </div>;
  }
  const now = brief.aiText?.nowJa ?? brief.now;
  const why = brief.aiText?.whyJa ?? brief.why;
  const next = brief.aiText?.nextJa ?? brief.next;
  const providerIssue = brief.aiDiagnostics?.errorCode;
  const providerMessage = providerIssue === 'credit_balance_exhausted'
    ? 'AI停止: 前払い残高不足'
    : ['organization_spend_limit_exceeded', 'project_spend_limit_exceeded'].includes(providerIssue ?? '')
      ? 'AI停止: 支出上限'
      : ['organization_usage_limit_exceeded', 'insufficient_quota'].includes(providerIssue ?? '')
        ? 'AI停止: 利用枠不足'
        : ['rate_limit_exceeded', 'slow_down'].includes(providerIssue ?? '')
          ? 'AI更新待ち: 呼出し制限'
          : null;
  return <div className="at-brief" data-argus-contract="market-brief-v1"
    aria-label="今の市場（売買権限なし）">
    <small>ARGUSの今日の見立て</small>
    <p className="at-brief__unavailable-title">{brief.generationWorker?.status === 'RUNNING' ? <TriangleStepLoader label={briefWaitingTitle(brief)} /> : briefWaitingTitle(brief)}</p>
    {updateState}
    {brief.unifiedStatus && brief.unifiedStatus !== 'GENERATED' && <p role="status">
      {providerMessage ?? gateNote ?? (brief.generationWorker?.status === 'RUNNING' ? '更新中'
        : ['FAILED', 'INVALID_RESPONSE', 'UNAVAILABLE'].includes(brief.generationWorker?.status ?? '')
          ? '更新失敗' : '更新待ち')}
      {brief.lastSuccessfulAiAt && <small> 最終成功 {new Date(brief.lastSuccessfulAiAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</small>}
    </p>}
    <details className="at-brief__fallback"><summary>取得済みの情報を見る</summary>
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
    </details>
    <CreditConditionsDetails brief={brief} /><MarketAnalysisHistory key="saved-history" />
  </div>;
};
