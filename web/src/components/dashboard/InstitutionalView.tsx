import React from 'react';
import { autoQueueTranslations } from '../../lib/queueRequests';

// INSTITUTIONAL VIEW inside the asset card (v10.147). A NAMED institutional VIEW is
// reported context — never a named trading position. Public metadata only; the full
// article opens at the source. Relation to the move is labelled, not asserted.
// v12.0.6 (owner: ニュースが英語のまま): displayTitleJaを主表示にし(未翻訳は
// 「翻訳待ち」+原文折りたたみ)、英語見出しは自動で翻訳キューへ。古い記事(>14日)は
// サーバー側で除外済み。

interface IntelItem {
  title: string; titleJa?: string | null; institutionId?: string | null; publishedAt?: string | null;
  accessClass: string; canonicalUrl?: string | null; stance?: string;
  category?: string; contentType?: string;
  displayTitleJa?: string | null; titleOriginal?: string | null; translationStatus?: string | null;
  ageHours?: number | null;
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
      .then((r) => r.json()).then((j) => {
        if (!alive) return;
        const its: IntelItem[] = j.items || [];
        setItems(its);
        // 未翻訳の英語見出しを可視翻訳キューへ(dedupe済み・24/365 cronが排出)
        const pend = its
          .filter((it) => it.translationStatus === 'pending' && it.titleOriginal)
          .map((it) => ({ titleOriginal: String(it.titleOriginal),
                          source: it.institutionId ?? undefined,
                          publishedAt: it.publishedAt ?? undefined }));
        if (pend.length) autoQueueTranslations(`inst-view|${symbol}`, 'institutional-view', symbol, '', pend);
      }).catch(() => {});
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
          {/* 主表示は常に日本語(displayTitleJa)。未翻訳は「翻訳待ち」+原文折りたたみ */}
          <a className="iv-title" href={it.canonicalUrl || '#'} target="_blank" rel="noopener noreferrer">
            {it.displayTitleJa || it.titleJa || it.title}
          </a>
          {it.translationStatus === 'pending' && it.titleOriginal && (
            <details>
              <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>原文を見る</summary>
              <p style={{ margin: '2px 0 0', fontSize: 11, color: 'var(--text-sub)' }}>{it.titleOriginal}</p>
            </details>
          )}
          {it.isNamedView && it.notConfirmed.length > 0 && (
            <div className="iv-nc">未確認: {it.notConfirmed.join(' / ')}</div>
          )}
          <div className="iv-meta">{it.publishedAt || ''} · {ACCESS_JA[it.accessClass] ?? '公開メタデータ'}{it.category === 'INSTITUTIONAL_RESEARCH_VIEW' ? '(見解であり建玉ではない)' : ''}</div>
        </div>
      ))}
    </div>
  );
};
