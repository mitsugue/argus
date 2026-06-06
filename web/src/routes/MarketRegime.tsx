import React from 'react';
import { PageShell, Placeholder } from './PageShell';
import { todayJudgment } from '../mock/dashboard';
import '../components/dashboard/Dashboard.css';

const REGIME_GLOSSARY: { tag: string; gloss: string }[] = [
  { tag: 'Risk On',              gloss: 'Equities and high-beta leading; defensives lag.' },
  { tag: 'Risk Off',              gloss: 'Defensives lead; equities and credit weaken.' },
  { tag: 'Event Risk',            gloss: 'Major scheduled catalyst within the window; entries throttled.' },
  { tag: 'Rates Pressure',        gloss: 'Yields rising — duration assets and growth multiples compress.' },
  { tag: 'Liquidity Tightening',  gloss: 'CB policy or financial conditions are tightening.' },
  { tag: 'JPY Shock',             gloss: 'USD/JPY moving fast; intervention risk elevated.' },
  { tag: 'Gold Hedge',            gloss: 'Gold leading on macro stress or real-yield reversal.' },
  { tag: 'Crypto Heat',           gloss: 'BTC/ETH overextended, funding elevated.' },
  { tag: 'Capitulation',          gloss: 'Forced selling; sentiment washed out.' },
  { tag: 'Buyable Pullback',      gloss: 'Healthy reset in an intact uptrend.' },
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
              <span className="hero__tag" key={r} style={{ fontSize: 12, padding: '4px 10px' }}>
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
          <span className="section-head__title">Regime glossary</span>
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

      <Placeholder
        title="Capital-flow visualization (supporting layer)"
        note="The old bubble view will return here as a supporting visual only — not the main UI."
      />
    </PageShell>
  );
};
