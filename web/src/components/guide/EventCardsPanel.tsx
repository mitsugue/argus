import '../dashboard/Dashboard.css';
import React from 'react';
import { useEventCards, type EventCard } from '../../hooks/useEventCards';

// EventCard v2 panel (v11) — the canonical research object made VISIBLE and honest.
// Each row shows the discipline: corroboration, trigger ROLE (candidate vs confirmed),
// and what confirmation is still MISSING. Renders nothing when there are no events, so
// it can never claim activity that isn't there.

const CORR_JA: Record<string, string> = {
  none: '裏取りなし', single_source: '単一ソース', multi_source: '複数独立ソース',
  official: '公式', market_confirmed: '市場が確認', official_and_market_confirmed: '公式＋市場確認',
};
const ROLE_JA: Record<string, { ja: string; tone: string }> = {
  confirmed_cause: { ja: '原因確定', tone: 'var(--value-positive,#34d399)' },
  probable_catalyst: { ja: '有力な引き金候補', tone: 'var(--value-positive,#34d399)' },
  candidate_catalyst: { ja: '引き金候補（確定でない）', tone: 'var(--amber,#fbbf24)' },
  vulnerability_context: { ja: '脆弱性の文脈', tone: 'var(--amber,#fbbf24)' },
  background_theme: { ja: '背景テーマ', tone: 'var(--text-muted)' },
  unknown: { ja: '不明', tone: 'var(--text-muted)' },
};

const Card: React.FC<{ c: EventCard }> = ({ c }) => {
  const role = ROLE_JA[c.triggerRole || 'unknown'] || ROLE_JA.unknown;
  return (
    <div className="mdepth__row" style={{ alignItems: 'flex-start', flexDirection: 'column', gap: 3 }}
         title={c.decisionImpact?.downgradeReasonJa || ''}>
      <span className="mdepth__label" style={{ whiteSpace: 'normal' }}>
        {(c.directAssets && c.directAssets.length ? c.directAssets.join(',') + ' · ' : '')}
        {c.headline || c.eventType}
      </span>
      <span style={{ fontSize: 11, color: 'var(--text-sub)' }}>
        <span style={{ color: role.tone, fontWeight: 600 }}>{role.ja}</span>
        {' · 裏取り: '}{CORR_JA[c.corroborationLevel || 'none'] || c.corroborationLevel}
        {typeof c.confidenceFinal === 'number' ? ` · 確信度 ${Math.round(c.confidenceFinal * 100)}%` : ''}
        {c.missingConfirmations && c.missingConfirmations.length
          ? ` · 不足: ${c.missingConfirmations.length}件` : ' · 不足なし'}
      </span>
    </div>
  );
};

export const EventCardsPanel: React.FC = () => {
  const d = useEventCards();
  const items = d?.items || [];
  if (!items.length) return null;    // never claim events that aren't there
  return (
    <section className="mdepth">
      <div className="section-head">
        <span className="section-head__title">Event Intelligence — EventCard v2</span>
        <span className="section-head__count">{items.length} 件</span>
      </div>
      <div className="card mdepth__card">
        <p className="mdepth__lead">
          イベントを正典オブジェクトとして扱います。<b>単一ソースは「原因確定」にしない・テーマだけでは判断を動かさない・
          不足している裏取りを必ず明示</b>します（連想≠原因）。
        </p>
        <div className="mdepth__grid">
          {items.map((c) => <Card key={c.cardId} c={c} />)}
        </div>
        <p className="mdepth__note">「引き金候補」は原因確定ではありません。公式確認＋市場確認がそろって初めて「原因確定」。</p>
      </div>
    </section>
  );
};
