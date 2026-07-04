import React from 'react';
import type { PortfolioExposure } from '../../domain/positionExposure';
import { READINESS_TONE } from '../../domain/positionExposure';
import { jpDisplay } from '../../lib/displayName';

// V11.8.0 — PORTFOLIO EXPOSURE on Today. Held-position risks first (a held
// asset's problem outranks any watchlist signal), then concentration/theme/
// currency exposure and add-more readiness. HONESTY: no holdings configured →
// say so plainly and show watchlist-theme context only. Never a trade order.

const LEVEL_TONE: Record<string, string> = {
  critical: 'var(--value-negative)', high: 'var(--value-negative)',
  medium: 'var(--amber, #fbbf24)', low: 'var(--text-muted)', unknown: 'var(--text-faint)',
};

export const PositionRiskSection: React.FC<{ exposure: PortfolioExposure }> = ({ exposure: pe }) => {
  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">PORTFOLIO EXPOSURE</span>
        <span className="section-head__count">保有リスク点検 · 売買指示なし</span>
      </div>

      {pe.noHoldings ? (
        <p style={{ fontSize: 12, color: 'var(--text-sub)', margin: '4px 0', lineHeight: 1.7 }}>
          ポジション数量・取得単価が未入力のため、保有リスクは暫定です。
          Watchlistの銘柄行で数量と取得単価を入力すると、集中度・テーマ偏り・買い増し余地を判定します
          (データは端末内のみ・どこにも送信されません)。
        </p>
      ) : pe.base.holdings.length === 0 ? (
        <p style={{ fontSize: 12, color: 'var(--text-sub)', margin: '4px 0', lineHeight: 1.7 }}>
          保有は入力済みですが価格が未取得のため、比率・集中度の判定を一時保留しています(価格取得後に自動計算)。
          保有銘柄: {Object.values(pe.notes).filter((n) => n.held).map((n) => jpDisplay(n.symbol, n.name)).join(' / ') || '—'}
        </p>
      ) : (
        <>
          {/* top risks — held first */}
          {pe.risks.length > 0 ? pe.risks.slice(0, 4).map((r, i) => (
            <div key={`${r.symbol}-${r.riskType}-${i}`}
                 style={{ borderLeft: `2px solid ${LEVEL_TONE[r.riskLevel] || 'var(--line)'}`,
                          paddingLeft: 8, margin: '6px 0' }}>
              <p style={{ margin: 0, fontSize: 12 }}>
                <b style={{ color: LEVEL_TONE[r.riskLevel] }}>{r.riskLevel.toUpperCase()}</b>
                <span style={{ marginLeft: 6, color: 'var(--text-sub)' }}>{r.whyJa}</span>
              </p>
              <p style={{ margin: '1px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
                次に確認: {r.checkNextJa}
              </p>
            </div>
          )) : (
            <p style={{ fontSize: 12, color: 'var(--text-faint)', margin: '4px 0' }}>
              集中度・含み損・イベントの面で優先度の高いリスクは検出されていません。
            </p>
          )}

          {/* exposure strip */}
          <p style={{ margin: '6px 0 0', fontSize: 11.5, color: 'var(--text-sub)' }}>
            テーマ: {pe.byTheme.slice(0, 4).map((t) => `${t.ja} ${t.pct.toFixed(0)}%`).join(' / ')}
            {pe.jpyPct != null && pe.usdPct != null && (
              <span style={{ marginLeft: 8 }}>通貨: ¥{pe.jpyPct.toFixed(0)}% / ${pe.usdPct.toFixed(0)}%</span>
            )}
          </p>
          {pe.top1Symbol && pe.top1Pct != null && pe.singleNameRisk !== 'low' && (
            <p style={{ margin: '2px 0 0', fontSize: 11.5, color: 'var(--text-sub)' }}>
              最大集中: <b>{jpDisplay(pe.top1Symbol, pe.notes[pe.top1Symbol]?.name)}</b> {pe.top1Pct.toFixed(0)}%
              <b style={{ marginLeft: 4, color: LEVEL_TONE[pe.singleNameRisk ?? 'low'] }}>
                {pe.singleNameRisk === 'critical' ? '危険水準' : pe.singleNameRisk === 'high' ? '高い' : 'やや高い'}
              </b>
            </p>
          )}

          {/* add-more readiness — held assets that are NOT freely addable */}
          {(() => {
            const capped = Object.values(pe.notes)
              .filter((n) => n.held && n.readiness !== 'add_allowed_small' && n.readiness !== 'monitor');
            if (capped.length === 0) return null;
            return (
              <p style={{ margin: '4px 0 0', fontSize: 11.5, color: 'var(--text-sub)' }}>
                買い増し注意:{' '}
                {capped.slice(0, 5).map((n, i) => (
                  <span key={n.symbol}>
                    {i > 0 && ' / '}
                    <b>{jpDisplay(n.symbol, n.name)}</b>
                    <span style={{ color: READINESS_TONE[n.readiness], marginLeft: 3 }}>{n.readinessJa}</span>
                  </span>
                ))}
              </p>
            );
          })()}
        </>
      )}

      {pe.provisionalNoteJa && !pe.noHoldings && (
        <p style={{ margin: '4px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>{pe.provisionalNoteJa}</p>
      )}
      <p style={{ margin: '4px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
        数量・取得単価・評価額はこの端末内でのみ計算(サーバー送信なし)。リスク点検であり売買指示ではありません。
      </p>
    </section>
  );
};

export default PositionRiskSection;
