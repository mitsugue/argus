import React from 'react';
import './MarketInstitutionalSection.css';

// §18 #3 — MARKET-WIDE INSTITUTIONAL INTELLIGENCE (max 3, only when material).
// A cross-market strategy / named institutional view shown ONCE at the top and
// linking to the affected assets. A reported view — never a trading position.
// Renders nothing when there is no material institutional intelligence.

interface IntelItem {
  title: string; institutionId?: string | null; publishedAt?: string | null;
  canonicalUrl?: string | null; stance?: string; contentType?: string;
  linkedAssets?: string[]; linkedThemes?: string[]; sourceId?: string;
}

const INST_NAME: Record<string, string> = {
  jpmorgan: 'JPMorgan', goldman_sachs: 'Goldman Sachs', morgan_stanley: 'Morgan Stanley',
  bank_of_america: 'BofA', citi: 'Citi', ubs: 'UBS', barclays: 'Barclays', jefferies: 'Jefferies',
  bernstein: 'Bernstein', nomura: 'Nomura', daiwa: 'Daiwa', mizuho: 'Mizuho',
  blackrock: 'BlackRock', citadel: 'Citadel', bridgewater: 'Bridgewater',
};
const STANCE_JA: Record<string, string> = { cautious: '慎重', constructive: '強気寄り', neutral: '中立' };
const STANCE_TONE: Record<string, string> = {
  cautious: 'var(--value-negative)', constructive: 'var(--value-positive)', neutral: 'var(--text-muted)',
};
// "material" = a named institution + a strategy/analyst-action or a non-neutral stance.
const MATERIAL_TYPES = new Set([
  'STRATEGY_OUTLOOK', 'RESEARCH_NOTE', 'EARNINGS_PREVIEW',
  'ANALYST_UPGRADE', 'ANALYST_DOWNGRADE', 'PRICE_TARGET_CHANGE', 'ESTIMATE_REVISION',
]);

export const MarketInstitutionalSection: React.FC = () => {
  const [items, setItems] = React.useState<IntelItem[] | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) return;
    let alive = true;
    fetch(`${backend.replace(/\/$/, '')}/api/argus/institutional-intelligence`)
      .then((r) => r.json()).then((j) => { if (alive) setItems(j.items || []); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const material = React.useMemo(() => {
    if (!items) return [];
    return items
      .filter((it) => it.institutionId &&
        (MATERIAL_TYPES.has(it.contentType || '') || (it.stance && it.stance !== 'neutral')))
      .slice(0, 3);
  }, [items]);

  if (material.length === 0) return null;

  return (
    <section className="mis">
      <div className="mis-head">
        <span className="mis-title">C.A.O.S.</span>
        <span className="mis-sub">Corroborated Analyst &amp; Official Signals · 機関の見解(建玉ではない)</span>
      </div>
      {material.map((it, i) => (
        <div className="mis-row" key={i}>
          <div className="mis-l1">
            <span className="mis-inst">{INST_NAME[it.institutionId!] ?? it.institutionId}</span>
            {it.stance && (
              <span className="mis-stance" style={{ color: STANCE_TONE[it.stance] }}>
                {STANCE_JA[it.stance] ?? it.stance}
              </span>
            )}
            {(it.linkedAssets || []).slice(0, 4).map((a) => (
              <span className="mis-asset" key={a}>{a}</span>
            ))}
          </div>
          <a className="mis-headline" href={it.canonicalUrl || '#'} target="_blank" rel="noopener noreferrer">
            {it.title}
          </a>
          <div className="mis-meta">{it.publishedAt || ''} · 公開メタデータ</div>
        </div>
      ))}
    </section>
  );
};
