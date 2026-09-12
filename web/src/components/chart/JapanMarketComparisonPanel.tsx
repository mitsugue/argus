import React from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { JapanMarketComparisonChart } from './JapanMarketComparisonChart';

export function JapanMarketComparisonPanel({ horizon }: { horizon: number }) {
  const state = useJapanMarketComparison(horizon);
  return <div className="jp-comparison-panel" data-argus-contract="jp-market-comparison-runtime-v1" aria-busy={state.loading}>
    {state.loading && <p role="status">日経平均の過去比較を更新中です。</p>}
    {state.error && <p role="status">
      {state.document ? '過去比較の更新を取得できないため、前回成功分を表示しています。' : '日経平均の過去比較に必要なデータを取得できていません。'}
      <button type="button" onClick={state.retry}>再取得</button>
    </p>}
    {state.lastSuccessfulAcquisitionAt && <p className="jp-comparison__scale">指数データの最終取得：
      {new Date(state.lastSuccessfulAcquisitionAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} JST</p>}
    {state.document && <JapanMarketComparisonChart document={state.document} />}
  </div>;
}
