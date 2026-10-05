import { TriangleStepLoader } from '../common/TriangleStepLoader';
import React, { useState } from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { JapanMarketComparisonChart } from './JapanMarketComparisonChart';
import { NikkeiResearchChart } from './NikkeiResearchChart';

export function JapanMarketComparisonPanel({ horizon }: { horizon: number }) {
  const state = useJapanMarketComparison(horizon);
  return <div className="jp-comparison-panel" data-argus-contract="jp-market-comparison-runtime-v1" aria-busy={state.loading}>
    {state.loading && <p><TriangleStepLoader label={state.document ? "前回の比較を表示しながら更新しています" : "日経平均の過去比較を読み込んでいます"} /></p>}
    {state.error && <p role="status">
      {state.document ? '過去比較の更新を取得できないため、前回成功分を表示しています。' : '日経平均の過去比較に必要なデータを取得できていません。'}
      <button type="button" onClick={state.retry}>再取得</button>
    </p>}
    {state.lastSuccessfulAcquisitionAt && <p className="jp-comparison__scale">指数データの最終取得：
      {new Date(state.lastSuccessfulAcquisitionAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} JST</p>}
    {state.document && <JapanMarketComparisonChart document={state.document} />}
  </div>;
}

/** Numerical comparisons have their own period; saved explanations keep theirs. */
export function JapanMarketHorizonComparison() {
  const [horizon, setHorizon] = useState<5 | 10 | 20>(5);
  const [mode, setMode] = useState<'research' | 'comparison'>('research');
  return <section id="today-nikkei-chart" aria-label="最新の日経平均の過去比較">
    <h3>日経平均の水準と見通し</h3>
    <div className="jp-comparison-periods" role="group" aria-label="チャートの表示">
      <button type="button" aria-pressed={mode === 'research'} onClick={() => setMode('research')}>価格の目盛りと参考予測</button>
      <button type="button" aria-pressed={mode === 'comparison'} onClick={() => setMode('comparison')}>従来の過去比較</button>
    </div>
    {mode === 'research' ? <NikkeiResearchChart /> : <>
    <p>保存したAI解説とは別に、取得済みの価格と市場条件で計算した参考経路です。</p>
    <div className="jp-comparison-periods" role="group" aria-label="見通しの期間">
      {([5, 10, 20] as const).map(period => <button key={period} type="button"
        aria-pressed={horizon === period} onClick={() => setHorizon(period)}>
        {period}営業日先
      </button>)}
    </div>
    <JapanMarketComparisonPanel key={horizon} horizon={horizon} />
    </>}
  </section>;
}
