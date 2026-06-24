import React from 'react';
import { useImportantEvents, type ImportantEvent, type EventImpact } from '../../hooks/useImportantEvents';
import { useLocale, t, pick } from '../../i18n';
import type { RouteKey } from '../NavRail';
import './ImportantEventsCard.css';

// IMPORTANT EVENTS — teaches the owner WHY a macro event matters before they look
// at individual assets (v10.138). Compact rows, top event expanded. Impact = how
// strongly markets may move (violet/amber/blue/gray tokens), NEVER a direction.
// No forecast/consensus is fabricated.

const IMPACT_TOKEN: Record<EventImpact, string> = {
  critical: 'var(--event-critical)', high: 'var(--event-high)',
  medium: 'var(--event-medium)', low: 'var(--event-low)',
};
const IMPACT_ICON: Record<EventImpact, string> = { critical: '◆', high: '▲', medium: '●', low: '·' };
const IMPACT_KEY: Record<EventImpact, 'ie.impact.critical' | 'ie.impact.high' | 'ie.impact.medium' | 'ie.impact.low'> = {
  critical: 'ie.impact.critical', high: 'ie.impact.high', medium: 'ie.impact.medium', low: 'ie.impact.low',
};
const COUNTDOWN_JA: Record<string, string> = { 'D': '本日', 'D-1': '明日', 'D-3': '数日内', 'D-7': '1週間内', 'D+1': '昨日', 'normal': '' };

function timeOnly(jst: string | null): string {
  if (!jst) return '';
  const m = jst.match(/(\d{1,2}:\d{2})/);
  return m ? `${m[1]} JST` : '';
}

const EventRow: React.FC<{ e: ImportantEvent; open: boolean }> = ({ e, open }) => {
  const loc = useLocale();
  const impact = e.displayImpact;
  const color = IMPACT_TOKEN[impact] ?? IMPACT_TOKEN.low;
  const countdown = loc === 'ja' ? (COUNTDOWN_JA[e.countdown] || e.countdown) : e.countdown;
  const novice = pick(e.noviceEn, e.noviceJa);
  const actionUntil = pick(e.actionUntilEn, e.actionUntilJa);
  const released = e.lifecycle === 'RELEASED' || e.lifecycle === 'REACTION_PENDING';
  const assets = (e.linkedAssets || []).slice(0, 4).join(' · ') || 'US10Y · USDJPY · QQQ';
  const nextReview = t('ie.nextReviewTmpl').replace('{assets}', assets);
  const impactLabel = t(IMPACT_KEY[impact]);
  const when = [e.date, timeOnly(e.jstTime), released ? t('ie.released') : countdown].filter(Boolean).join(' · ');

  return (
    <details className="ie-row" open={open}>
      <summary aria-label={`${e.eventCode}, ${impactLabel}, ${when}`}>
        <span className="ie-when">{when}</span>
        <span className="ie-code">{e.eventCode}</span>
        <span className="ie-impact" style={{ color }} aria-hidden>{IMPACT_ICON[impact]} {impactLabel}</span>
      </summary>
      <div className="ie-body">
        <p className="ie-line"><span className="ie-k">{t('ie.whyMatters')}</span>{novice}</p>
        {!released && (
          <p className="ie-line"><span className="ie-k">{t('ie.untilRelease')}</span><b style={{ color: actionUntil.includes('禁止') || actionUntil.toUpperCase().includes('BLOCKED') ? 'var(--value-negative)' : 'var(--text-main)' }}>{actionUntil}</b></p>
        )}
        <p className="ie-line"><span className="ie-k">{t('ie.nextReview')}</span>{nextReview}</p>
        <p className="ie-data">{t('ie.forecast')}: {t('ie.unavailable')} · {t('ie.previous')}: {t('ie.unavailable')}{e.source ? ` · ${e.source}` : ''}</p>
      </div>
    </details>
  );
};

interface Props { onNavigate?: (key: RouteKey) => void; }

export const ImportantEventsCard: React.FC<Props> = ({ onNavigate }) => {
  useLocale();
  const { data } = useImportantEvents();
  const events = data?.events ?? [];
  if (events.length === 0) return null;          // calm: nothing shown when no high/critical events
  const shown = events.slice(0, 5);              // desktop ≤5; CSS hides beyond 3 on mobile

  return (
    <section id="important-events" className="ie-card" aria-label="Important events">
      <div className="ie-head">
        <span className="ie-title">{t('ie.title')}</span>
        <button className="ie-viewall" onClick={() => onNavigate?.('regime')}>{t('ie.viewAll')} →</button>
      </div>
      <div className="ie-rows">
        {shown.map((e, i) => <EventRow key={e.eventId} e={e} open={i === 0} />)}
      </div>
      <p className="ie-note">{t('ie.impactNote')}</p>
    </section>
  );
};
