import React from 'react';
import type { MarketBrief } from '../../lib/marketBrief';

export function NumericalResearchDetails({ brief }: { brief: MarketBrief }) {
  const references = brief.unifiedContext?.researchPackages;
  if (!Array.isArray(references) || !references.length) return null;
  return <details className="argus-editorial__evidence"><summary>比較に使った研究と、確認できていない範囲</summary>
    <p>保存済みの計算結果を参照しています。日経平均と連動ETFは別の対象です。研究の読み取り成功は、将来の予測力を保証しません。</p>
    {references.map(row => <section key={row.packageId}><h3>{row.labelJa}</h3>
      <p>{row.coverage.historyStart}〜{row.coverage.historyEnd} · {row.coverage.historyCount}営業日</p>
      {Object.entries(row.horizons).map(([period, horizon]) => <p key={period}>{period}営業日先 · 有効標本 {horizon.effectiveSampleCount ?? '未確認'}件 · {horizon.calibrationStatus === 'poor_calibration' ? '基準モデル未達' : ['insufficient_sample', 'insufficient_history'].includes(horizon.calibrationStatus ?? '') ? '標本不足' : '独立期間の予測力受入は未完了'}</p>)}
      <small>参照ID {row.packageId}<br/>版 {row.packageVersion}</small>
    </section>)}
  </details>;
}
