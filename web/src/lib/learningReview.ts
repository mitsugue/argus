// V11.15.0 — Learning Dashboard (device-local TS port of argus_learning_review.py).
// 端末内の判断記録から「どのラベルが役に立っているか」を控えめに集計する。
// 学習用の傾向であり、成績でも将来保証でも売買指示でもない。
// サンプル規律: n<5=履歴不足 / 5-19=初期傾向 / 20-49=中程度 / 50+=強め(慎重)。

import { listDQ, type DQRecord } from './decisionQuality';
import { listNotifications } from './notifications';

export const MIN_SAMPLE = 5;
export const CAVEAT_JA = 'まだ履歴が少ないため、成績としては扱わないでください。';

export interface LearningMetric {
  metricType: string; label: string; sampleCount: number; enoughSamples: boolean;
  supportedCount: number; contradictedCount: number; mixedCount: number;
  avgReturn1d: number | null; avgReturn3d: number | null;
  avgReturn5d: number | null; avgReturn20d: number | null;
  avgMaxDrawdown5d: number | null; avgMaxRunup5d: number | null;
  winRate5d: number | null;
  confidence: 'low' | 'medium' | 'high' | 'insufficient';
  interpretationJa: string; caveatJa: string;
  examples: { symbol: string; asOf: string; return5d: number | null }[];
}

const avg = (xs: (number | null | undefined)[]): number | null => {
  const v = xs.filter((x): x is number => typeof x === 'number');
  return v.length ? Math.round((v.reduce((a, b) => a + b, 0) / v.length) * 100) / 100 : null;
};
const confFor = (n: number) => n < MIN_SAMPLE ? 'insufficient' as const
  : n < 20 ? 'low' as const : n < 50 ? 'medium' as const : 'high' as const;

function interpret(mt: string, label: string, n: number, sup: number, con: number,
  r5: number | null, dd5: number | null, ru5: number | null): string {
  if (n < MIN_SAMPLE) return `「${label}」はまだ履歴不足です(n=${n})。傾向の判定は保留します。`;
  const early = n < 20 ? `(初期傾向・n=${n})` : `(n=${n})`;
  const judged = sup + con;
  if (mt === 'decision_context' && label === 'avoid_chase') {
    if (judged >= 3 && sup > con && dd5 != null && dd5 <= -2) return `追いかけ注意は今のところ有効に見えます。急騰後に一度押すケースが多いです${early}。`;
    if (judged >= 3 && con > sup) return `追いかけ注意が保守的すぎる可能性があります。ただし履歴数が十分か確認が必要です${early}。`;
    return `追いかけ注意の有効性はまだ判定中です${early}。`;
  }
  if (mt === 'decision_context' && label === 'add_only_on_pullback') {
    if (judged >= 3 && sup > con) return `押し目限定は機能しています${early}。`;
    if (judged >= 3 && con > sup) return `押し目待ちで機会を逃している可能性があります${early}。`;
    return `押し目限定の有効性はまだ判定中です${early}。`;
  }
  if (mt === 'supply_demand_rank' && ['S', 'A', 'B'].includes(label)) {
    if (r5 != null && r5 >= 1.5 && sup >= con) return `需給${label}は継続上昇の補助材料として機能している可能性があります${early}。`;
    if (r5 != null && r5 < 0) return `需給${label}だけでは上昇継続を説明できない可能性があります${early}。`;
    return `需給${label}のその後は中立圏です${early}。`;
  }
  if (mt === 'supply_demand_rank' && ['D', 'E'].includes(label)) {
    if (r5 != null && r5 <= -1) return `需給${label}の後は弱含みやすい傾向が出ています${early}。`;
    return `需給${label}の警戒が過剰だった可能性を確認中です${early}。`;
  }
  if (mt === 'supply_demand_condition' && label === 'improving_but_heavy') {
    if (ru5 != null && r5 != null && ru5 >= 2 && r5 < ru5 - 1.5) return `「改善中だが買い残が重い」は上昇しても戻り売りで失速しやすい傾向です${early}。`;
    if (r5 != null && r5 >= 2) return `「改善中だが買い残が重い」でも続伸したケースが出ています${early}。`;
    return `「改善中だが買い残が重い」の帰結を追跡中です${early}。`;
  }
  if ((mt === 'supply_demand_condition' && label === 'squeeze_prone')
    || (mt === 'flow_class' && label === 'short_covering')) {
    if (ru5 != null && r5 != null && ru5 >= 3 && r5 < ru5 - 2) return `踏み上げ候補は短期上昇後に失速しやすい傾向が出ています${early}。`;
    return `踏み上げ候補は短期上昇後に失速しやすいかを確認中です${early}。`;
  }
  return `「${label}」の傾向を追跡中です${early}。`;
}

function metricFrom(mt: string, label: string, recs: DQRecord[]): LearningMetric {
  const outs = recs.map((r) => r.outcome).filter(Boolean) as NonNullable<DQRecord['outcome']>[];
  const n = recs.length;
  const sup = outs.filter((o) => o.outcomeInterpretation === 'supported').length;
  const con = outs.filter((o) => o.outcomeInterpretation === 'contradicted').length;
  const r5s = outs.map((o) => o.outcomeReturn5d).filter((x): x is number => typeof x === 'number');
  const r5 = avg(outs.map((o) => o.outcomeReturn5d));
  const dd5 = avg(outs.map((o) => o.maxDrawdown5d));
  const ru5 = avg(outs.map((o) => o.maxRunup5d));
  return {
    metricType: mt, label, sampleCount: n, enoughSamples: n >= MIN_SAMPLE,
    supportedCount: sup, contradictedCount: con,
    mixedCount: outs.filter((o) => o.outcomeInterpretation === 'mixed').length,
    avgReturn1d: avg(outs.map((o) => o.outcomeReturn1d)),
    avgReturn3d: avg(outs.map((o) => o.outcomeReturn3d)),
    avgReturn5d: r5, avgReturn20d: avg(outs.map((o) => o.outcomeReturn20d)),
    avgMaxDrawdown5d: dd5, avgMaxRunup5d: ru5,
    winRate5d: r5s.length >= 20 ? Math.round(r5s.filter((x) => x > 0).length / r5s.length * 100) / 100 : null,
    confidence: confFor(n),
    interpretationJa: interpret(mt, label, n, sup, con, r5, dd5, ru5),
    caveatJa: n < 20 ? CAVEAT_JA : 'これは学習用の傾向であり、将来を保証する成績ではありません。',
    examples: recs.slice(0, 3).map((r) => ({ symbol: r.symbol, asOf: r.asOf.slice(0, 10),
      return5d: r.outcome?.outcomeReturn5d ?? null })),
  };
}

/** 主要ラベルのメトリクスを端末内記録から計算。 */
export function computeLearningMetrics(): LearningMetric[] {
  const recs = listDQ();
  const out: LearningMetric[] = [];
  const by = (pred: (r: DQRecord) => boolean) => recs.filter(pred);
  for (const ctx of ['avoid_chase', 'add_only_on_pullback', 'add_allowed_small', 'wait', 'monitor']) {
    out.push(metricFrom('decision_context', ctx, by((r) => r.decisionContext === ctx)));
  }
  for (const rank of ['A', 'B', 'D', 'E']) {
    out.push(metricFrom('supply_demand_rank', rank, by((r) => r.supplyDemandRank === rank)));
  }
  out.push(metricFrom('supply_demand_condition', 'improving_but_heavy',
    by((r) => r.supplyDemandCondition === 'improving_but_heavy')));
  out.push(metricFrom('supply_demand_condition', 'squeeze_prone',
    by((r) => r.supplyDemandCondition === 'squeeze_prone')));
  out.push(metricFrom('flow_class', 'short_covering', by((r) => r.flowClass === 'short_covering')));
  return out;
}

export interface LearningSummary {
  records: number; withOutcome: number; enough: number; tooEarly: number;
  dismissedAlerts: number;
}
export function learningSummary(metrics: LearningMetric[]): LearningSummary {
  const recs = listDQ();
  return {
    records: recs.length,
    withOutcome: recs.filter((r) => r.outcome && (r.outcome.outcomeStatus === 'partial' || r.outcome.outcomeStatus === 'complete')).length,
    enough: metrics.filter((m) => m.enoughSamples).length,
    tooEarly: metrics.filter((m) => !m.enoughSamples).length,
    dismissedAlerts: listNotifications().filter((n) => n.deliveryState === 'dismissed').length,
  };
}

/** 銘柄カード用: この銘柄の過去パターン一行(履歴不足なら正直に)。 */
export function pastPatternLineJa(symbol: string): string | null {
  const recs = listDQ().filter((r) => r.symbol.toUpperCase() === symbol.toUpperCase());
  if (!recs.length) return null;
  if (recs.length < MIN_SAMPLE) return `過去記録${recs.length}件 — 履歴不足のため傾向判定は保留(貯まると表示されます)。`;
  const sup = recs.filter((r) => r.outcome?.outcomeInterpretation === 'supported').length;
  const con = recs.filter((r) => r.outcome?.outcomeInterpretation === 'contradicted').length;
  return `過去記録${recs.length}件: ラベル支持${sup}/反証${con}(初期傾向・成績ではありません)。`;
}

/** Pro Handoff / AI Review 用の学習サマリ行。 */
export function lrHandoffTextJa(): string {
  const ms = computeLearningMetrics();
  const s = learningSummary(ms);
  const L = ['## Learning / Decision Review (device-local)',
    `記録${s.records}件 / 結果あり${s.withOutcome} / 判定可能ラベル${s.enough} / 履歴不足${s.tooEarly}`];
  const notable = ms.filter((m) => m.enoughSamples && (m.supportedCount + m.contradictedCount) >= 3).slice(0, 4);
  for (const m of notable) L.push(`- ${m.interpretationJa}`);
  if (!notable.length) L.push('- まだどのラベルも履歴不足です。判定は保留中。');
  L.push(`注意: ${CAVEAT_JA} 学習用の傾向であり売買指示ではない。`);
  return L.join('\n');
}
