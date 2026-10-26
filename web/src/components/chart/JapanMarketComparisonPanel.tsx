import { TriangleStepLoader } from '../common/TriangleStepLoader';
import React, { useState } from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import { readableBriefEdition } from '../../lib/presentationIntent';
import { comparisonAgreement } from '../../lib/japanMarketComparison';
import { JapanMarketComparisonChart } from './JapanMarketComparisonChart';
import { NikkeiResearchChart } from './NikkeiResearchChart';

export function JapanMarketComparisonPanel({ horizon }: { horizon: number }) {
  const state = useJapanMarketComparison(horizon);
  // The same edition Today shows (a retained one when the newest is not readable).
  const { brief: responseBrief } = useMarketBrief();
  const brief = readableBriefEdition(responseBrief) ?? responseBrief;
  const agreement = comparisonAgreement(brief?.calculationSnapshots?.[String(horizon)]?.comparison, state.document,
    horizon, brief ? brief.aiDiagnostics?.completedAt ?? brief.generatedAt : null);
  return <div className="jp-comparison-panel" data-argus-contract="jp-market-comparison-runtime-v1" aria-busy={state.loading}>
    {state.loading && <p><TriangleStepLoader label={state.document ? "更新中" : "読み込み中"} /></p>}
    {state.error && <p role="status">
      {state.document ? '更新失敗・前回分' : '取得できません'}
      <button type="button" onClick={state.retry}>再取得</button>
    </p>}
    {state.lastSuccessfulAcquisitionAt && <p className="jp-comparison__scale">取得{' '}
      {new Date(state.lastSuccessfulAcquisitionAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</p>}
    {agreement && <p className="jp-comparison__scale" data-comparison-agreement={agreement.kind}>{agreement.textJa}</p>}
    {state.document && <JapanMarketComparisonChart document={state.document} />}
  </div>;
}

/** The Nikkei 225 chart card: the price scale with the reference forecast and
 * the past similar periods.
 * 2026-10-26 (owner): the past similar periods chart is offered again; the
 * future lines view is removed because the reference forecast now carries the
 * newest drawn line. */
export function JapanMarketHorizonComparison() {
  const [horizon, setHorizon] = useState<5 | 10 | 20>(5);
  const [mode, setMode] = useState<'research' | 'comparison'>('research');
  return <section id="today-nikkei-chart" aria-label="日経平均のチャート">
    <h3>NIKKEI 225</h3>
    <div className="jp-comparison-periods jp-comparison-views" role="group" aria-label="チャートの表示">
      <button type="button" aria-pressed={mode === 'research'} onClick={() => setMode('research')}>価格の目盛りと<wbr />参考予測</button>
      <button type="button" aria-pressed={mode === 'comparison'} onClick={() => setMode('comparison')}>過去の似た局面</button>
    </div>
    {mode === 'research' ? <NikkeiResearchChart /> : <>
      <div className="jp-comparison-periods" role="group" aria-label="見通しの期間">
        {([5, 10, 20] as const).map(period => <button key={period} type="button"
          aria-pressed={horizon === period} onClick={() => setHorizon(period)}>{period}営業日先</button>)}
      </div>
      <JapanMarketComparisonPanel key={horizon} horizon={horizon} />
    </>}
  </section>;
}
