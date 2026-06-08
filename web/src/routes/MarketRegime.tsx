import React, { useEffect } from 'react';
import { PageShell } from './PageShell';
import { CapitalRotationBoard } from '../components/regime/CapitalRotationBoard';
import { RegimeMatrix } from '../components/regime/RegimeMatrix';
import { FredRatesSnapshot } from '../components/regime/FredRatesSnapshot';
import { regimeMatrix, regimeSummary, rotationBoard } from '../mock/regime';
import '../components/dashboard/Dashboard.css';

// Regime tag keys stay English (UI vocabulary); gloss is JP — intentional
// bilingual split, not a transition mistake.
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

// Order per v8.1 spec:
//   Subtitle → Capital Rotation Board (primary) → Regime Matrix
//   (supporting, compact) → Regime Summary → Glossary.
// The bubble / SectorBlob viz is retired from the main experience.
export const MarketRegime: React.FC = () => {
  // When arriving via the "full board" link, scroll to the board after layout
  // is ready (double rAF), landing cleanly below the sticky header (the section
  // carries scroll-margin-top). Fixes the iPhone half-wrong jump.
  useEffect(() => {
    let target: string | null = null;
    try { target = sessionStorage.getItem('argus.scrollTo'); } catch { /* ignore */ }
    if (target !== 'full-board') return;
    try { sessionStorage.removeItem('argus.scrollTo'); } catch { /* ignore */ }
    const id = requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        document.getElementById('full-board')?.scrollIntoView({ block: 'start' });
      }),
    );
    return () => cancelAnimationFrame(id);
  }, []);

  return (
    <PageShell
      title="Market Regime"
      subtitle="Current cross-asset environment and capital rotation. Visualizations support action labels; they are not trading signals by themselves."
    >
      <section id="full-board" className="regime-anchor">
        <div className="section-head">
          <span className="section-head__title">Capital Rotation Board</span>
          <span className="section-head__count">
            {rotationBoard.length} asset classes
          </span>
        </div>
        <CapitalRotationBoard rows={rotationBoard} />
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Regime Matrix</span>
          <span className="section-head__count">supporting view</span>
        </div>
        <RegimeMatrix state={regimeMatrix} compact />
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Regime Summary</span>
        </div>
        <div className="card">
          <p style={{
            fontSize: 13,
            color: 'var(--text-main)',
            fontWeight: 500,
            marginBottom: 8,
          }}>
            {regimeSummary.headline}
          </p>
          <p style={{
            fontSize: 13,
            color: 'var(--text-sub)',
            lineHeight: 1.7,
          }}>
            {regimeSummary.body}
          </p>
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">FRED Rates Snapshot</span>
          <span className="section-head__count">first live data source</span>
        </div>
        <FredRatesSnapshot />
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
