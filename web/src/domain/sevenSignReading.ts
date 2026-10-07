import type { SignEventStudy } from '../types/japanMarketComparison';

// Describe the current rule's direction; neither the rule nor its count is a forecast.
export const CURRENT_SIGNAL_DIRECTION: Record<string, 'warning' | 'support'> = {
  D01: 'warning', D02: 'warning', D03: 'support', D04: 'warning',
  D05: 'support', D06: 'support', D07: 'support',
};
export function signalDirectionJa(family: string): string {
  const direction = CURRENT_SIGNAL_DIRECTION[family];
  return direction === 'warning' ? '警戒' : direction === 'support' ? '上昇を支える' : '向き未確認';
}
const VERDICT: Record<string, string> = {
  INSUFFICIENT_SAMPLE: '件数不足', NOT_ABOVE_BASELINE: '基準を上回らない',
  ABOVE_BASELINE: '基準を上回る', NOT_EVALUABLE: '測定規則なし',
};
const pct = (value: number | null | undefined) => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
export function signalPerformanceJa(family: string, study: SignEventStudy | null | undefined, currentBasis?: string | null): string {
  if (family === 'D04' && currentBasis === 'ARGUS_ESTIMATE_MARKET_CAP_WEIGHTED_FORWARD') {
    return '最新PERの警戒条件は未定義。旧方式の成績とは別です。';
  }
  if (!study || study.status !== 'AVAILABLE') return '過去の成績：未取得';
  const condition = study.conditions[family];
  if (!condition) return '過去の成績：未取得';
  if (condition.status === 'NOT_EVALUABLE') return '過去の成績：測定規則なし';
  const metric = condition.horizons[String(study.primaryHorizon)];
  const direction = condition.expects === 'FALL' ? '下落' : condition.expects === 'RISE' ? '上昇' : '向き未確認';
  return `過去${study.primaryHorizon}営業日後の${direction} ${pct(metric?.hitShare)}（普段 ${pct(metric?.baselineHitShare)}）・${metric?.evaluated ?? 0}件・${VERDICT[condition.status] ?? '未確認'}`;
}


/** Distance to the measurement boundary, never time-to-hit or a forecast. */
export function warningDistanceJa(row: import('./marketSignals').MarketSignalRow): string | null {
  const d = row.distance;
  if (!d || !['ACTIVE', 'CLEAR'].includes(row.state) || !Number.isFinite(d.signedFromBoundary)) return null;
  if (d.atBoundary) return d.boundaryCounts ? '基準ちょうど・成立中' : '基準ちょうど・まだ成立していません';
  const delta = Math.abs(d.signedFromBoundary);
  const compact = (value: number) => value.toLocaleString('ja-JP', { maximumSignificantDigits: 6 });
  const amount = d.unit === 'JPY' ? delta >= 1e8 ? `${compact(delta / 1e8)}億円` : `${compact(delta)}円`
    : d.unit === 'JPY_EPS' ? `${compact(delta)}円`
    : d.unit === 'INDEX_RATIO' ? `指数比の差 ${compact(delta)}`
    : d.unit === 'FRACTION' ? `${compact(delta * 100)}ポイント`
    : d.unit === 'RATIO' ? `${compact(delta)}倍` : `MACDの差 ${compact(delta)}`;
  const side = d.signedFromBoundary > 0 ? '高い' : '低い';
  return row.state === 'ACTIVE' ? `基準より${amount}${side}・成立中`
    : d.operator === '>=' ? `成立まであと${amount}の上昇`
    : d.operator === '>' ? `基準まであと${amount}（上回ると成立）`
    : `基準まであと${amount}（下回ると成立）`;
}
