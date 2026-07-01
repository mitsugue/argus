import React from 'react';

// INSTITUTIONAL VIEW inside the asset card (v10.147). A NAMED institutional VIEW is
// reported context — never a named trading position. Public metadata only; the full
// article opens at the source. Relation to the move is labelled, not asserted.

interface IntelItem {
  title: string; titleJa?: string | null; institutionId?: string | null; publishedAt?: string | null;
  accessClass: string; canonicalUrl?: string | null; stance?: string;
  category?: string; contentType?: string;
  relation: string; relationLabelJa: string; isNamedView: boolean; notConfirmed: string[];
}

// §5 category badge — separates a reported VIEW from a rating ACTION / disclosed
// POSITION so the two are never conflated (an analyst downgrade ≠ the firm selling).
const CATEGORY_JA: Record<string, string> = {
  INSTITUTIONAL_RESEARCH_VIEW: '見解', ANALYST_ACTION: 'アナリスト・アクション',
  DISCLOSED_POSITION: '開示ポジション', OFFICIAL: '公式', MARKET_NEWS: 'ニュース',
};
const CONTENT_JA: Record<string, string> = {
  ANALYST_UPGRADE: '格上げ', ANALYST_DOWNGRADE: '格下げ', PRICE_TARGET_CHANGE: '目標株価変更',
  ESTIMATE_REVISION: '業績予想修正', REGULATORY_FILING: '大量保有等の開示', STRATEGY_OUTLOOK: '見通し',
};
const ACCESS_JA: Record<string, string> = {
  PUBLIC_FULLTEXT: '公開全文', PUBLIC_METADATA: '公開メタデータ', SUBSCRIBER_CAPTURE: '購読者取込',
  LINK_ONLY: 'リンクのみ',
};

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
            {it.category && <span className="iv-cat">{CATEGORY_JA[it.category] ?? it.category}</span>}
            {it.contentType && CONTENT_JA[it.contentType] && <span className="iv-ct">{CONTENT_JA[it.contentType]}</span>}
            <span className="iv-rel" style={{ color: REL_TONE[it.relation] ?? 'var(--text-muted)' }}>{it.relationLabelJa}</span>
          </div>
          <a className="iv-title" href={it.canonicalUrl || '#'} target="_blank" rel="noopener noreferrer">{it.titleJa || it.title}</a>
          {it.isNamedView && it.notConfirmed.length > 0 && (
            <div className="iv-nc">未確認: {it.notConfirmed.join(' / ')}</div>
          )}
          <div className="iv-meta">{it.publishedAt || ''} · {ACCESS_JA[it.accessClass] ?? '公開メタデータ'}{it.category === 'INSTITUTIONAL_RESEARCH_VIEW' ? '(見解であり建玉ではない)' : ''}</div>
        </div>
      ))}
    </div>
  );
};
