import React from 'react';
import { computeLearningMetrics, learningSummary, CAVEAT_JA, type LearningMetric } from '../../lib/learningReview';

// V11.15.0 — LEARNING DASHBOARD (Core Portfolio)。ARGUSのラベルが「その後」
// どうだったかの控えめな集計。学習用であり成績・将来保証・売買指示ではない。

const CONF_JA: Record<string, string> = {
  insufficient: '履歴不足', low: '初期傾向', medium: '中程度', high: '傾向あり(慎重)',
};
const CONF_TONE: Record<string, string> = {
  insufficient: 'var(--text-faint)', low: 'var(--text-muted)',
  medium: 'var(--accent)', high: 'var(--value-positive)',
};
const fmtPct = (v: number | null) => v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;

export const LearningDashboardCard: React.FC = () => {
  const metrics = React.useMemo(() => computeLearningMetrics(), []);
  const s = React.useMemo(() => learningSummary(metrics), [metrics]);
  const shown = metrics.filter((m) => m.sampleCount > 0);

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">LEARNING DASHBOARD</span>
        <span className="section-head__count">判断の学習レビュー · 端末内のみ</span>
      </div>
      <div className="card cmd-alloc">
        <div className="cmd-alloc__note" style={{ fontSize: 12, color: 'var(--text-sub)' }}>
          {CAVEAT_JA} これは学習用の傾向で、将来の保証でも売買指示でもありません。
        </div>
        <div className="cmd-alloc__note">
          記録 {s.records}件 / 結果あり {s.withOutcome} / 判定可能ラベル {s.enough} / 履歴不足 {s.tooEarly}
          {s.dismissedAlerts > 0 && <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>閉じられた通知 {s.dismissedAlerts}件(ノイズ指標として記録中)</span>}
        </div>
        {shown.length === 0 ? (
          <p className="cmd-alloc__empty">
            記録がまだありません。保有数量を入力してTodayを開くと毎日自動で記録され、数週間で初期傾向が見え始めます。
          </p>
        ) : shown.map((m: LearningMetric) => (
          <div key={m.metricType + m.label} style={{ borderTop: '1px solid var(--line)', padding: '6px 0' }}>
            <p style={{ margin: 0, fontSize: 12 }}>
              <b>{m.label}</b>
              <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>({m.metricType})</span>
              <b style={{ marginLeft: 6, fontSize: 10.5, color: CONF_TONE[m.confidence] }}>{CONF_JA[m.confidence]}</b>
              <span style={{ marginLeft: 6, fontSize: 10.5, color: 'var(--text-faint)' }}>n={m.sampleCount}</span>
            </p>
            <p style={{ margin: '2px 0 0', fontSize: 11.5, color: 'var(--text-sub)', lineHeight: 1.6 }}>
              {m.interpretationJa}
            </p>
            {m.enoughSamples && (
              <p style={{ margin: '1px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
                その後平均: 1d {fmtPct(m.avgReturn1d)} / 3d {fmtPct(m.avgReturn3d)} / 5d {fmtPct(m.avgReturn5d)} / 20d {fmtPct(m.avgReturn20d)}
                {m.winRate5d != null && ` / 5d勝率 ${(m.winRate5d * 100).toFixed(0)}%`}
                {m.avgMaxDrawdown5d != null && ` / 平均押し ${fmtPct(m.avgMaxDrawdown5d)}`}
              </p>
            )}
            {m.examples.length > 0 && m.enoughSamples && (
              <p style={{ margin: '1px 0 0', fontSize: 10, color: 'var(--text-faint)' }}>
                例: {m.examples.map((e) => `${e.symbol}(${e.return5d != null ? fmtPct(e.return5d) : '結果待ち'})`).join(' / ')}
              </p>
            )}
          </div>
        ))}
        <p className="cmd-alloc__note" style={{ fontSize: 10 }}>
          集計は端末内の判断記録のみから計算(サーバー送信なし)。「改善中だが買い残が重い」は
          需給良好と別枠で追跡。P0/P1は価格が動かなくても誤りとは判定しません。
        </p>
      </div>
    </section>
  );
};

export default LearningDashboardCard;
