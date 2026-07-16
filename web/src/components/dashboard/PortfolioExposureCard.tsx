import React from 'react';
import type { AssetItem } from '../../types/assetItem';
import { fmtMoney, fmtSigned, type ExposureSummary } from '../../lib/portfolio';

// V12.2.12 — Portfolio Exposure(旧AssetStrategySection内から移設・計算不変)。
// 置き場所: Positions & Risk(ポートフォリオ横断はAsset Deskでなくこちら)。
// Compact portfolio header: per-currency totals + unrealized P/L + JPY-combined
// allocation. All math is client-side (lib/portfolio.ts); holdings never leave
// the device. Shown only once at least one holding is entered.

const GENRE_COLOR: Record<string, string> = {
  jp: 'var(--blue)', us: 'var(--green)', funds: 'var(--amber)', crypto: 'var(--cyan)',
};

export const PortfolioExposureCard: React.FC<{
  assets: AssetItem[];
  exp: ExposureSummary;
}> = ({ assets, exp }) => {
  const anyHolding = assets.some((a) => (a.quantity ?? 0) > 0 && a.avgCost != null);
  if (!anyHolding) {
    return (
      <div className="card exp exp--hint">
        <span className="exp__title">Portfolio Exposure</span>
        <p className="exp__hint">Asset Deskの銘柄カード(OWNER POSITION)で「保有数量・平均取得単価」を入力すると、ここに評価額・含み損益・配分が表示されます(データはこの端末内のみ)。</p>
      </div>
    );
  }
  const plColor = (v: number) => (v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text-sub)');
  return (
    <div className="card exp">
      <div className="exp__head">
        <span className="exp__title">Portfolio Exposure</span>
        <span className="exp__note">端末内のみ・未実現損益</span>
      </div>
      <div className="exp__totals">
        {(['JPY', 'USD'] as const).filter((c) => exp.totals[c].value > 0).map((c) => (
          <span key={c} className="exp__total">
            <b>{fmtMoney(c, exp.totals[c].value)}</b>
            <span style={{ color: plColor(exp.totals[c].pl) }}>
              {' '}{fmtSigned(c, exp.totals[c].pl)}
              （{exp.totals[c].cost > 0 ? `${exp.totals[c].pl >= 0 ? '+' : ''}${((exp.totals[c].pl / exp.totals[c].cost) * 100).toFixed(1)}%` : '—'}）
            </span>
          </span>
        ))}
        {exp.combinedJpy != null && exp.totals.USD.value > 0 && exp.totals.JPY.value > 0 && (
          <span className="exp__combined">
            合計 ≈ {fmtMoney('JPY', exp.combinedJpy)}
            <span style={{ color: plColor(exp.combinedPlJpy ?? 0) }}>{' '}{fmtSigned('JPY', exp.combinedPlJpy ?? 0)}</span>
            {exp.usdJpy != null && <span className="exp__fx">（USD/JPY {exp.usdJpy}）</span>}
          </span>
        )}
      </div>
      {exp.byGenre.length > 0 && (
        <>
          <div className="exp__bar" aria-hidden>
            {exp.byGenre.map((g) => (
              <span key={g.key} style={{ width: `${g.pct}%`, background: GENRE_COLOR[g.key] }} />
            ))}
          </div>
          <div className="exp__legend">
            {exp.byGenre.map((g) => (
              <span key={g.key}>
                <span className="exp__dot" style={{ background: GENRE_COLOR[g.key] }} />
                {g.title} {g.pct.toFixed(1)}%
              </span>
            ))}
          </div>
        </>
      )}
      {exp.unpriced.length > 0 && (
        <p className="exp__unpriced">ライブ価格未取得のため対象外: {exp.unpriced.join(', ')}（投信の基準価額は未対応）</p>
      )}
    </div>
  );
};
