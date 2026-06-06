import React from 'react';
import { PageShell } from './PageShell';
import { RegimeMatrix } from '../components/regime/RegimeMatrix';
import { CapitalRotationBoard } from '../components/regime/CapitalRotationBoard';
import { regimeMatrix, rotationBoard } from '../mock/regime';
import '../components/dashboard/Dashboard.css';

// Regime tag keys stay English (UI vocabulary) — gloss is JP for the
// transition phase.
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
      subtitle="Current cross-asset environment and capital rotation. Visualizations support the action labels; they are not trading signals by themselves."
    >
      <section>
        <div className="section-head">
          <span className="section-head__title">Regime Matrix</span>
          <span className="section-head__count">classification, not forecast</span>
        </div>
        <RegimeMatrix state={regimeMatrix} />
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Capital Rotation Board</span>
          <span className="section-head__count">{rotationBoard.length} asset classes</span>
        </div>
        <CapitalRotationBoard rows={rotationBoard} />
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
