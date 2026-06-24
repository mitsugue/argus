import React from 'react';

// INSTITUTIONAL VIEW inside the asset card (v10.147). A NAMED institutional VIEW is
// reported context — never a named trading position. Public metadata only; the full
// article opens at the source. Relation to the move is labelled, not asserted.

interface IntelItem {
  title: string; titleJa?: string | null; institutionId?: string | null; publishedAt?: string | null;
  accessClass: string; canonicalUrl?: string | null; stance?: string;
  relation: string; relationLabelJa: string; isNamedView: boolean; notConfirmed: string[];
}

const REL_TONE: Record<string, string> = {
  IMMEDIATE_TRIGGER: 'var(--value-negative)', LIKELY_RELATED: 'var(--event-high)',
  AMPLIFIER: 'var(--event-medium)', VULNERABILITY: 'var(--text-sub)',
  BACKGROUND_ONLY: 'var(--text-muted)', CONTRADICTION: 'var(--value-positive)', UNCONFIRMED: 'var(--text-muted)',
};
const INST_NAME: Record<string, string> = {
  jpmorgan: 'JPMorgan', goldman_sachs: 'Goldman Sachs', morgan_stanley: 'Morgan Stanley',
  nomura: 'Nomura', daiwa: 'Daiwa', mizuho: 'Mizuho', blackrock: 'BlackRock', citadel: 'Citadel',
};

export const InstitutionalView: React.FC<{ symbol: string }> = ({ symbol }) => {
  const [items, setItems] = React.useState<IntelItem[] | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) return;
    let alive = true;
    fetch(`${backend.replace(/\/$/, '')}/api/argus/events/${encodeURIComponent(symbol)}/institutional-intelligence`)
      .then((r) => r.json()).then((j) => { if (alive) setItems(j.items || []); }).catch(() => {});
    return () => { alive = false; };
  }, [symbol]);

  if (!items || items.length === 0) return null;
  return (
    <div className="uac-sec">
      <div className="uac-sec-t">INSTITUTIONAL VIEW</div>
      {items.slice(0, 3).map((it, i) => (
        <div className="iv-row" key={i}>
          <div className="iv-l1">
            <span className="iv-inst">{it.institutionId ? (INST_NAME[it.institutionId] ?? it.institutionId) : '—'}</span>
            <span className="iv-rel" style={{ color: REL_TONE[it.relation] ?? 'var(--text-muted)' }}>{it.relationLabelJa}</span>
          </div>
          <a className="iv-title" href={it.canonicalUrl || '#'} target="_blank" rel="noopener noreferrer">{it.titleJa || it.title}</a>
          {it.isNamedView && it.notConfirmed.length > 0 && (
            <div className="iv-nc">未確認: {it.notConfirmed.join(' / ')}</div>
          )}
          <div className="iv-meta">{it.publishedAt || ''} · 公開メタデータ(見解であり建玉ではない)</div>
        </div>
      ))}
    </div>
  );
};
