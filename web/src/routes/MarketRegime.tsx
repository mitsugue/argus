import React from 'react';
import { PageShell } from './PageShell';
import { SectorBlob } from '../components/SectorBlob';
import { todayJudgment } from '../mock/dashboard';
import '../components/dashboard/Dashboard.css';

// Tag keys stay English (UI vocabulary) — gloss is rendered in JP for
// the user's transition phase.
const REGIME_GLOSSARY: { tag: string; gloss: string }[] = [
  { tag: 'Risk On',               gloss: '株式・ハイベータが牽引、ディフェンシブは遅れる。' },
  { tag: 'Risk Off',              gloss: 'ディフェンシブが先導、株式・クレジットが弱含み。' },
  { tag: 'Event Risk',            gloss: 'ウィンドウ内に主要触媒。新規エントリーを抑制。' },
  { tag: 'Rates Pressure',        gloss: '金利上昇 — デュレーション資産とグロース倍率が圧縮。' },
  { tag: 'Liquidity Tightening',  gloss: '中銀政策または金融条件が引き締まっている。' },
  { tag: 'JPY Shock',             gloss: 'USD/JPY が急変、介入リスク高まる。' },
  { tag: 'Gold Hedge',            gloss: 'マクロ不安または実質利回り反転で金が先行。' },
  { tag: 'Crypto Heat',           gloss: 'BTC/ETH 過熱、ファンディング上昇。' },
  { tag: 'Capitulation',          gloss: '投げ売り発生、センチメント枯渇。' },
  { tag: 'Buyable Pullback',      gloss: '健全な押し目、上昇トレンドは継続。' },
];

export const MarketRegime: React.FC = () => {
  return (
    <PageShell
      title="Market Regime"
      subtitle="Classification of the current environment. Supports the judgment; never replaces it."
    >
      <section>
        <div className="section-head">
          <span className="section-head__title">Active regime</span>
        </div>
        <div className="card">
          <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
            {todayJudgment.regime.map((r) => (
              <span
                className="hero__tag"
                key={r}
                style={{ fontSize: 12, padding: '4px 10px' }}
              >
                {r}
              </span>
            ))}
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-sub)', lineHeight: 1.65 }}>
            {todayJudgment.summary}
          </p>
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Capital concentration</span>
          <span className="section-head__count">
            supporting layer
          </span>
        </div>
        <div className="regime-viz">
          <SectorBlob />
        </div>
        <div className="regime-viz__caption">
          <span>
            Bubble size ≈ relative weight by asset class. Tap or pinch a
            bubble to drill into its sub-composition.
          </span>
          <span className="regime-viz__caption-hint">Mock data</span>
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Regime glossary</span>
          <span className="section-head__count">{REGIME_GLOSSARY.length} tags</span>
        </div>
        <div className="card" style={{ padding: 0 }}>
          <div className="core-list" style={{ padding: '4px 22px' }}>
            {REGIME_GLOSSARY.map((g) => (
              <div className="core-row" key={g.tag}>
                <div className="core-row__body">
                  <span className="core-row__top">{g.tag}</span>
                  <span className="core-row__reason">{g.gloss}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </PageShell>
  );
};
