import React from 'react';
import { useImportantEvents, type ImportantEvent, type EventImpact } from '../../hooks/useImportantEvents';
import { useMacroEventAnalysis, type MacroAnalysis } from '../../hooks/useMacroEventAnalysis';
import { useDashboardEvents } from '../../hooks/useDashboardEvents';
import { deriveDashboardEventDisplayState, type DashboardEvent, type DashboardEventReaction } from '../../lib/dashboardEventState';
import { useLocale, t, pick } from '../../i18n';
import type { RouteKey } from '../NavRail';
import { buildReviewPackMarkdown, copyPack } from '../../lib/reviewPack';
import { EVENT_DESC_JA } from '../../lib/eventLabels';
import './ImportantEventsCard.css';

// v11.4.1 tone → color for the unified state badge.
const STATE_TONE_COLOR: Record<string, string> = {
  pre: 'var(--event-high, #8b5cf6)', pending: 'var(--amber, #fbbf24)',
  post: 'var(--value-positive, #34d399)', checked: 'var(--value-positive, #34d399)',
  warning: 'var(--amber, #fbbf24)', neutral: 'var(--text-muted)',
};

function jstFromUtc(utc?: string | null): string {
  if (!utc) return '';
  const d = new Date(utc);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' }) + ' JST';
}

// v12.0.8 Part B (owner: CPIが「21:30 JST 発表前」で今日に見えた): イベントの
// 「いつ」は必ず 日付+JST時刻+D-count で表示する。日付が今日でも「本日」を明示。
// 日時が取れない場合は「日時未確認」と正直に言う(時刻だけの表示はしない)。
function eventWhenJa(utc?: string | null, fallbackDate?: string | null): string {
  if (!utc) return fallbackDate ? `${fallbackDate} · 時刻未確認` : '日時未確認';
  const d = new Date(utc);
  if (isNaN(d.getTime())) return '日時未確認';
  const jstDay = (x: Date) => x.toLocaleDateString('ja-JP', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit' });
  const md = d.toLocaleDateString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' });
  const hm = d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
  const today = jstDay(new Date());
  const evDay = jstDay(d);
  const diffDays = Math.round((new Date(evDay.replace(/\//g, '-')).getTime() - new Date(today.replace(/\//g, '-')).getTime()) / 86_400_000);
  const rel = diffDays === 0 ? '本日' : diffDays > 0 ? `あと${diffDays}日` : `${-diffDays}日前`;
  return `${md} ${hm} JST · ${rel}`;
}

const RISK_TONE_JA: Record<string, string> = {
  risk_on: 'リスクオン', risk_off: 'リスクオフ', rates_up: '金利上昇', rates_down: '金利低下',
  mixed: 'まちまち', unknown: '方向感不明',
};

// v11.5: quantitative reaction fields (US10Y/USDJPY/SPY/QQQ/VIX/…). Null fields are
// omitted; if nothing is populated we show 市場反応データ未取得 (never fake numbers).
function reactionChips(mr?: DashboardEventReaction): { chips: string[]; tone: string | null } {
  if (!mr) return { chips: [], tone: null };
  const chips: string[] = [];
  const pushPct = (label: string, v?: number | null) => {
    if (typeof v === 'number') chips.push(`${label} ${v >= 0 ? '+' : ''}${v.toFixed(1)}%`);
  };
  if (typeof mr.us10yMoveBp === 'number') chips.push(`US10Y ${mr.us10yMoveBp >= 0 ? '+' : ''}${mr.us10yMoveBp.toFixed(0)}bp`);
  pushPct('USDJPY', mr.usdJpyMovePct);
  pushPct('SPY', mr.spyMovePct);
  pushPct('QQQ', mr.qqqMovePct);
  pushPct('VIX', mr.vixMovePct);
  pushPct('BTC', mr.btcMovePct);
  const tone = mr.riskTone && mr.riskTone !== 'unknown' ? (RISK_TONE_JA[mr.riskTone] || null) : null;
  return { chips, tone };
}

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
        <AskAIEvent code={e.eventCode} titleJa={e.title}
          stateJa={released ? '発表済' : countdown} whyJa={novice}
          linkedAssets={e.linkedAssets || []} />
      </div>
    </details>
  );
};

// v11.20.0 — 「このイベントをAIに相談」: Event Review Packをコピー(自動送信なし)。
const AskAIEvent: React.FC<{ code: string; titleJa: string; stateJa: string;
  whyJa?: string; linkedAssets: string[] }> = ({ code, titleJa, stateJa, whyJa, linkedAssets }) => {
  const [msg, setMsg] = React.useState<string | null>(null);
  return (
    <p className="ie-line" style={{ fontSize: 10.5 }}>
      <button type="button"
        style={{ fontSize: 10.5, cursor: 'pointer', background: 'transparent',
                 color: 'var(--accent)', border: '1px solid var(--line)',
                 borderRadius: 5, padding: '1px 8px' }}
        onClick={async () => {
          const md = buildReviewPackMarkdown({ packType: 'event', privacyMode: 'owner_copy',
            length: 'full', appVersion: __APP_VERSION__,
            event: { code, titleJa, stateJa, whyJa, linkedAssets,
              checksAfterJa: ['金利(US10Y)の初動', 'ドル円', '指数(SPY/QQQ/日経先物)', '関連銘柄の出来高'] } });
          setMsg(await copyPack(md) ? '✓ コピーしました' : 'コピー失敗');
          window.setTimeout(() => setMsg(null), 2500);
        }}>
        このイベントをAIに相談(コピー)
      </button>
      {msg && <span style={{ marginLeft: 6, color: 'var(--value-positive)' }}>{msg}</span>}
    </p>
  );
};

// v11.4.1 UNIFIED ROW — the single event surface. After release, official result +
// impact lead; the pre view drops to a collapsed "事前シナリオ（当時）". Released-pending
// shows "発表済み・公式結果取得中" (never a countdown). The pre scenario is ARGUS's own
// read — never called "consensus".
const UnifiedEventRow: React.FC<{ ev: DashboardEvent; open: boolean; lastRefresh?: string }>
  = ({ ev, open, lastRefresh }) => {
  const ds = deriveDashboardEventDisplayState(ev);
  const color = STATE_TONE_COLOR[ds.tone] ?? STATE_TONE_COLOR.neutral;
  const c = ev.caos || {};
  // v12.0.8: 日付+時刻+D-count を常時表示(「21:30 JSTだけで今日に見える」の根治)
  const when = eventWhenJa(ev.eventTimeUtc, ev.eventDate);
  const vColor = (VERDICT_JA[c.verdict || 'not_available'] || VERDICT_JA.not_available).tone;
  const preHistorical = (c.preScenarioJa || c.summaryJa) && ds.showPreAsHistorical ? (
    <details className="ie-hist">
      <summary style={{ color: 'var(--text-faint)', fontSize: 12, cursor: 'pointer' }}>事前シナリオ（当時）</summary>
      <p className="ie-line" style={{ color: 'var(--text-sub)' }}>{c.preScenarioJa || c.summaryJa}</p>
    </details>
  ) : null;

  return (
    <details className="ie-row" open={open}>
      <summary aria-label={`${ev.eventCode}, ${ds.released ? '発表済' : ev.stateLabelJa}, ${when}`}>
        <span className="ie-when">{when}</span>
        <span className="ie-code">{ev.eventCode}</span>
        {ds.stampBoxed ? (
          // v11.5: clear boxed "発表済" stamp so it's obvious the event has printed.
          <span className="ie-stamp" style={{
            color, borderColor: color, fontWeight: 700, fontSize: 12,
            border: `1.5px solid ${color}`, borderRadius: 4, padding: '1px 6px',
            letterSpacing: '0.05em', whiteSpace: 'nowrap',
          }} aria-hidden>{ds.stampJa}</span>
        ) : (
          <span className="ie-impact" style={{ color, fontWeight: 700 }} aria-hidden>{ds.stampJa}</span>
        )}
      </summary>
      <div className="ie-body">
        {/* v12.0.4 (owner): どんなイベントかの一言概要を先頭に */}
        {EVENT_DESC_JA[ev.eventCode] && (
          <p className="ie-line" style={{ color: 'var(--text-sub)' }}>
            <span className="ie-k">これは何</span>{EVENT_DESC_JA[ev.eventCode]}
          </p>
        )}
        {ds.showActualFirst && (
          <>
            <p className="ie-line"><span className="ie-k">公式結果</span><b>{ev.officialResult.headlineJa || '取得済み'}</b></p>
            {ds.showImpact && <p className="ie-line"><span className="ie-k">影響コメント</span>{c.impactCommentJa}</p>}
            {c.marketReactionJa && <p className="ie-line"><span className="ie-k">市場反応</span>{c.marketReactionJa}</p>}
            {(() => {
              const { chips, tone } = reactionChips(ev.marketReaction);
              if (chips.length > 0) {
                return <p className="ie-data">反応: {chips.join(' · ')}{tone ? ` ・ ${tone}` : ''}</p>;
              }
              // released with an official result but no quantitative reaction yet
              return <p className="ie-data" style={{ color: 'var(--text-faint)' }}>市場反応データ未取得</p>;
            })()}
            {ds.showAnswerCheck && (
              <p className="ie-line"><span className="ie-k">答え合わせ</span>
                <b style={{ color: vColor }}>{c.verdictJa}</b>{c.answerCheckJa ? ` — ${c.answerCheckJa}` : ''}</p>
            )}
            {!ds.showAnswerCheck && <p className="ie-line" style={{ color: 'var(--text-faint)' }}><span className="ie-k">答え合わせ</span>答え合わせ生成待ち</p>}
            {preHistorical}
          </>
        )}
        {ds.showPendingResult && (
          <>
            <p className="ie-line">発表時刻は通過。公式結果の取得待ち。</p>
            {(ev.officialResult.limitationsJa || []).length > 0 && (
              <p className="ie-data">{(ev.officialResult.limitationsJa || []).join(' / ')}</p>
            )}
            {preHistorical}
            <p className="ie-data">次回更新: 定期リフレッシュ{lastRefresh ? ` · 最終確認 ${String(lastRefresh).slice(11, 16)}Z` : ''}</p>
          </>
        )}
        {ds.showPreProminently && (
          <>
            {(c.preScenarioJa || c.summaryJa)
              ? <p className="ie-line"><span className="ie-k">AIシナリオ</span>{c.preScenarioJa || c.summaryJa}</p>
              : <p className="ie-line" style={{ color: 'var(--text-faint)' }}><span className="ie-k">AIシナリオ</span>生成待ち…</p>}
            {c.marketPricingJa && <p className="ie-line"><span className="ie-k">市場の織り込み</span>{c.marketPricingJa}</p>}
            {c.whatWouldSurpriseJa && <p className="ie-line"><span className="ie-k">サプライズ時</span>{c.whatWouldSurpriseJa}</p>}
            {(c.assetsToWatch || []).length > 0 && (
              <p className="ie-data">注目: {(c.assetsToWatch || []).join(' · ')} ・ AIシナリオはコンセンサスや売買指示ではありません</p>
            )}
          </>
        )}
        {/* v11.20.0: Event Review Pack copy(端末内合成・自動送信なし) */}
        <AskAIEvent code={ev.eventCode} titleJa={ev.title}
          stateJa={ds.released ? '発表済' : ev.stateLabelJa || '発表前'}
          whyJa={c.preScenarioJa || c.summaryJa}
          linkedAssets={c.assetsToWatch || []} />
      </div>
    </details>
  );
};

interface Props { onNavigate?: (key: RouteKey) => void; embedded?: boolean; }

// `embedded` = the lower block of the top command card (divider only, no card
// chrome) per spec §2. Standalone = its own card (used elsewhere).

// v11.14.0 (owner): 「カレンダーを見る」はMarket Contextのイベントカレンダー
// セクション先頭へ確実に着地させる(従来はページ遷移だけでスクロール位置が
// 中途半端に残った)。ページは非同期マウントなので短いリトライで探す。
function gotoCalendar(onNavigate?: (k: string) => void): void {
  onNavigate?.('regime');
  let tries = 0;
  let settles = 0;
  const tick = () => {
    const el = document.getElementById('event-calendar');
    if (el) {
      el.scrollIntoView({ block: 'start', behavior: 'auto' });
      // 上のセクション(Matrix等)が遅延マウントしてレイアウトが動くので、
      // 数回スクロールを当て直して着地を固定する。
      if (++settles < 5) setTimeout(tick, 350);
      return;
    }
    if (++tries < 12) setTimeout(tick, 180);
  };
  setTimeout(tick, 120);
}

export const ImportantEventsCard: React.FC<Props> = ({ onNavigate, embedded }) => {
  useLocale();
  const dash = useDashboardEvents();             // v11.4.1: unified event feed (preferred)
  const { data } = useImportantEvents();
  const analysis = useMacroEventAnalysis();      // v11.3.2: C.A.O.S. pre/post overlay (fallback)

  // Preferred path: the unified dashboard-events surface (single source of truth).
  if (dash && dash.items.length > 0) {
    const shown = dash.items.slice(0, 5);
    const lastRefresh = (dash.status?.lastHotRefreshAt as string) || undefined;
    return (
      <section id="important-events" className={embedded ? 'ie-embed' : 'ie-card'} aria-label="Important events">
        <div className="ie-head">
          <span className="ie-title">{t('ie.title')}</span>
          <button className="ie-viewall" onClick={() => gotoCalendar(onNavigate as never)}>{t('ie.viewAll')} →</button>
        </div>
        <div className="ie-rows">
          {shown.map((ev, i) => <UnifiedEventRow key={ev.displayEventId} ev={ev} open={i === 0} lastRefresh={lastRefresh} />)}
        </div>
        {/* v11.14.0 (owner): CAOS下段のイベント評価コーナーは廃止 — この先の予定も
            ここ(トップカード)に一覧。分析(概要/事前予想)は接近時に上の行へ昇格。 */}
        {(() => {
          const covered = new Set(dash.items.map((it) => String(it.eventCode || '').toUpperCase()));
          const upcoming = (data?.events ?? [])
            .filter((e) => (e.displayImpact === 'critical' || e.displayImpact === 'high')
              && !covered.has(String(e.eventCode || '').toUpperCase()))
            .slice(0, 4);
          if (!upcoming.length) return null;
          return (
            <div style={{ borderTop: '1px solid var(--line)', marginTop: 6, paddingTop: 4 }}>
              <p style={{ margin: 0, fontSize: 10.5, color: 'var(--text-faint)' }}>この先の重要イベント(接近すると上に昇格して事前予想が付きます)</p>
              {upcoming.map((e) => (
                <p key={e.eventId} style={{ margin: '2px 0 0', fontSize: 11.5, color: 'var(--text-sub)' }}>
                  <b>{e.eventCode}</b>
                  <span style={{ marginLeft: 6 }}>{e.date?.slice(5).replace('-', '/')}</span>
                  <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>影響:{e.displayImpact === 'critical' ? '重大' : '大'}</span>
                  {EVENT_DESC_JA[e.eventCode] && (
                    <span style={{ display: 'block', fontSize: 10.5, color: 'var(--text-faint)' }}>
                      {EVENT_DESC_JA[e.eventCode]}
                    </span>
                  )}
                </p>
              ))}
            </div>
          );
        })()}
        <p className="ie-note">{t('ie.impactNote')}</p>
      </section>
    );
  }

  // Fallback: legacy important-events + macro overlay (if /dashboard-events is unavailable).
  const events = data?.events ?? [];
  if (events.length === 0) return null;          // calm: nothing shown when no high/critical events
  const shown = events.slice(0, 5);              // desktop ≤5; CSS hides beyond 3 on mobile

  return (
    <section id="important-events" className={embedded ? 'ie-embed' : 'ie-card'} aria-label="Important events">
      <div className="ie-head">
        <span className="ie-title">{t('ie.title')}</span>
        <button className="ie-viewall" onClick={() => gotoCalendar(onNavigate as never)}>{t('ie.viewAll')} →</button>
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
