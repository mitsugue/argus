import React from 'react';
import { useImportantEvents, type ImportantEvent, type EventImpact } from '../../hooks/useImportantEvents';
import { useMacroEventAnalysis, type MacroAnalysis } from '../../hooks/useMacroEventAnalysis';
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

const VERDICT_JA: Record<string, { ja: string; tone: string }> = {
  hit: { ja: '概ね当たり', tone: 'var(--value-positive, #34d399)' },
  partial: { ja: '部分的', tone: 'var(--amber, #fbbf24)' },
  miss: { ja: '外れ', tone: 'var(--value-negative, #f87171)' },
  not_scoreable: { ja: '採点不可', tone: 'var(--text-muted)' },
  not_available: { ja: '未確認', tone: 'var(--text-muted)' },
};

// C.A.O.S. macro pre/post block (v11.3.2). PRE = ARGUS AIシナリオ (NOT a consensus).
// POST = preserved pre + verdict answer-check against the OFFICIAL result. Missing
// result → 公式結果待ち; missing pre → 採点不可 — never fabricated.
const CaosAnalysisBlock: React.FC<{ ai: MacroAnalysis; released: boolean }> = ({ ai, released }) => {
  const pre = ai.pre || {};
  const post = ai.post || {};
  const hasPre = !!(pre.argusScenarioJa || pre.summaryJa);
  if (!released) {
    if (!hasPre) return <p className="ie-line" style={{ color: 'var(--text-faint)' }}><span className="ie-k">AIシナリオ</span>生成待ち…</p>;
    return (
      <>
        <p className="ie-line"><span className="ie-k">AIシナリオ</span>{pre.argusScenarioJa || pre.summaryJa}</p>
        {pre.marketPricingJa && <p className="ie-line"><span className="ie-k">市場の織り込み</span>{pre.marketPricingJa}</p>}
        {pre.whatWouldSurpriseJa && <p className="ie-line"><span className="ie-k">サプライズ時</span>{pre.whatWouldSurpriseJa}</p>}
        {(pre.assetsToWatch || []).length > 0 && (
          <p className="ie-data">注目: {(pre.assetsToWatch || []).join(' · ')} ・ AIシナリオは売買指示ではありません</p>
        )}
      </>
    );
  }
  const v = VERDICT_JA[post.verdict || 'not_available'] || VERDICT_JA.not_available;
  return (
    <>
      {hasPre && <p className="ie-line"><span className="ie-k">事前予想(当時)</span>{pre.argusScenarioJa || pre.summaryJa}</p>}
      {ai.actual?.available
        ? <p className="ie-line"><span className="ie-k">公式結果</span>{ai.actual.headline || '取得済み'}</p>
        : <p className="ie-line" style={{ color: 'var(--text-faint)' }}><span className="ie-k">公式結果</span>公式結果待ち</p>}
      {!hasPre
        ? <p className="ie-line" style={{ color: 'var(--text-faint)' }}><span className="ie-k">答え合わせ</span>事前予想が保存されていないため答え合わせ不可</p>
        : (post.answerCheckJa || post.verdict) && (
            <p className="ie-line"><span className="ie-k">答え合わせ</span>
              <b style={{ color: v.tone }}>{v.ja}</b>{post.answerCheckJa ? ` — ${post.answerCheckJa}` : ''}</p>
          )}
      {post.marketReactionJa && <p className="ie-line"><span className="ie-k">市場反応</span>{post.marketReactionJa}</p>}
      {post.portfolioImpactJa && <p className="ie-line"><span className="ie-k">影響コメント</span>{post.portfolioImpactJa}</p>}
    </>
  );
};

const EventRow: React.FC<{ e: ImportantEvent; open: boolean; ai?: MacroAnalysis }> = ({ e, open, ai }) => {
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
        {ai && <CaosAnalysisBlock ai={ai} released={released} />}
        <p className="ie-data">{t('ie.forecast')}: {t('ie.unavailable')} · {t('ie.previous')}: {t('ie.unavailable')}{e.source ? ` · ${e.source}` : ''}</p>
      </div>
    </details>
  );
};

interface Props { onNavigate?: (key: RouteKey) => void; embedded?: boolean; }

// `embedded` = the lower block of the top command card (divider only, no card
// chrome) per spec §2. Standalone = its own card (used elsewhere).
export const ImportantEventsCard: React.FC<Props> = ({ onNavigate, embedded }) => {
  useLocale();
  const { data } = useImportantEvents();
  const analysis = useMacroEventAnalysis();      // v11.3.2: C.A.O.S. pre/post overlay
  const events = data?.events ?? [];
  if (events.length === 0) return null;          // calm: nothing shown when no high/critical events
  const shown = events.slice(0, 5);              // desktop ≤5; CSS hides beyond 3 on mobile

  return (
    <section id="important-events" className={embedded ? 'ie-embed' : 'ie-card'} aria-label="Important events">
      <div className="ie-head">
        <span className="ie-title">{t('ie.title')}</span>
        <button className="ie-viewall" onClick={() => onNavigate?.('regime')}>{t('ie.viewAll')} →</button>
      </div>
      <div className="ie-rows">
        {shown.map((e, i) => (
          <EventRow key={e.eventId} e={e} open={i === 0}
                    ai={analysis[e.eventId] || analysis[e.eventCode]} />
        ))}
      </div>
      <p className="ie-note">{t('ie.impactNote')}</p>
    </section>
  );
};
