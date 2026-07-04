import React from 'react';
import { useFlowAttributionList, FLOW_TONE, ACTION_TONE } from '../../hooks/useFlowAttribution';

// V11.7.0 — BIG MONEY / FLOW section on Today. Shows today's material watchlist
// movers with an evidence-based flow reading (大口買い集めの可能性/買い戻しの可能性/
// 個人の追随買い/売り抜け/狼狽売り…). HONESTY: 推定は推定と明示、実測(direct)と
// 推定(inferred)を分離、足りない証拠を常に表示。売買指示は一切出さない。

export const FlowAttributionSection: React.FC = () => {
  const { records, loading } = useFlowAttributionList();
  if (loading && records.length === 0) return null;

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">BIG MONEY / FLOW</span>
        <span className="section-head__count">{records.length}件 · 推定(売買指示なし)</span>
      </div>
      {records.length === 0 ? (
        <p style={{ fontSize: 12, color: 'var(--text-faint)', margin: '4px 0' }}>
          本日、判定対象になる大きな動き(±2%以上または出来高急増)はウォッチリストにありません。
        </p>
      ) : (
        records.slice(0, 6).map((r) => (
          <div key={r.id + r.symbol}
               style={{ borderLeft: `2px solid ${FLOW_TONE[r.direction] || 'var(--line)'}`,
                        paddingLeft: 8, margin: '6px 0' }}>
            <p style={{ margin: 0, fontSize: 12.5 }}>
              <b>{r.symbol}</b>
              {r.name && r.name !== r.symbol && (
                <span style={{ marginLeft: 4, color: 'var(--text-sub)' }}>{r.name}</span>
              )}
              {typeof r.changePct === 'number' && (
                <span style={{ marginLeft: 6,
                               color: r.changePct >= 0 ? 'var(--value-positive)' : 'var(--value-negative)' }}>
                  {r.changePct >= 0 ? '+' : ''}{r.changePct.toFixed(1)}%
                </span>
              )}
              <span style={{ marginLeft: 8, color: FLOW_TONE[r.direction] || 'var(--text-main)', fontWeight: 600 }}>
                {r.flowClassJa}
              </span>
              <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
                {r.directnessJa} · 確度{Math.round(r.confidence * 100)}%
              </span>
            </p>
            <p style={{ margin: '2px 0 0', fontSize: 11.5, color: 'var(--text-sub)', lineHeight: 1.6 }}>
              {r.ownerReadableWhyJa}
            </p>
            <p style={{ margin: '2px 0 0', fontSize: 11, color: 'var(--text-faint)' }}>
              <span style={{ color: ACTION_TONE[r.actionImplication] || 'var(--text-muted)', fontWeight: 600 }}>
                {r.actionImplicationJa}
              </span>
              <span style={{ marginLeft: 6 }}>次に確認: {r.checkNextJa}</span>
            </p>
            {r.missingEvidence.length > 0 && r.confidence < 0.65 && (
              <p style={{ margin: '1px 0 0', fontSize: 10, color: 'var(--text-faint)' }}>
                足りない証拠: {r.missingEvidence.slice(0, 3).join(' / ')}
              </p>
            )}
          </div>
        ))
      )}
      <p style={{ margin: '4px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
        値動き・出来高・信用/空売り・実測フロー(米国のみ)からの推定。「大口が動いた」と断定できるのは
        実測データがある場合のみ。売買指示ではありません。
      </p>
    </section>
  );
};

export default FlowAttributionSection;
