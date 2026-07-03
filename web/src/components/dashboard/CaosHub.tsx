import React from 'react';
import { useMarketNews } from '../../hooks/useMarketNews';
import { useImportantEvents } from '../../hooks/useImportantEvents';
import { useDownsideIncidents } from '../../hooks/useDownsideIncidents';
import { useNewsRadar } from '../../hooks/useNewsRadar';
import { useDashboardEvents } from '../../hooks/useDashboardEvents';
import { dashboardDedupeKey } from '../../lib/dashboardEventState';
import { newsDisplayTitleJa } from '../../lib/aiExplanationState';
import { autoQueueTranslations } from '../../lib/queueRequests';
import { useWatchtowerStatus } from '../../hooks/useWatchtowerStatus';
import { classifyFreshness, freshnessLabelJa, isPastMaterial } from '../../lib/newsFreshness';
import { OVERRIDE_LABEL_JA } from '../../domain/actionLevel';
import './CaosEvents.css';
import './MarketInstitutionalSection.css';
import './CaosHub.css';

// C.A.O.S. hub (v10.168) — the single intelligence card on Today, ALWAYS the 2nd card.
// Folds three tiers under one roof: ① 機関シグナル (named-institution views) ② イベント分析
// (概要/事前予想/事後) ③ ニュース (general market headlines).
// HONESTY (v11): "always present" ≠ "live". News is polled metadata (title/link), NOT a
// realtime feed, and a single headline is uncorroborated context — never a confirmed cause
// (see EventCard v2 discipline + the CAOS audit trail /api/argus/caos/audit). Institutional
// items are REPORTED VIEWS, never inferred trades. Decision-support only.

interface IntelItem {
  title: string; titleJa?: string | null; institutionId?: string | null;
  canonicalUrl?: string | null; stance?: string; contentType?: string; linkedAssets?: string[];
}
interface CaosEvent {
  eventId: string; eventCode: string; phase: 'pre' | 'post'; displayImpact: string;
  summaryJa?: string; preJa?: string; postJa?: string; headlineJa?: string; bodyJa?: string;
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
const MATERIAL_TYPES = new Set([
  'STRATEGY_OUTLOOK', 'RESEARCH_NOTE', 'EARNINGS_PREVIEW',
  'ANALYST_UPGRADE', 'ANALYST_DOWNGRADE', 'PRICE_TARGET_CHANGE', 'ESTIMATE_REVISION',
]);
const IMPACT_JA: Record<string, string> = { critical: '重大', high: '大', medium: '中', low: '小' };
// Corroboration badge (v10.170) — official > corroborated (>=2 independent families) > single.
// A 'single' (unverified) headline is shown muted so it reads as low-trust at a glance.
const CORROB: Record<string, { ja: string; cls: string }> = {
  official: { ja: '公式', cls: 'caoshub-corrob--official' },
  corroborated: { ja: '裏取り', cls: 'caoshub-corrob--ok' },
  single: { ja: '単一ソース', cls: 'caoshub-corrob--single' },
};
const PHASE: Record<string, { ja: string; tone: string }> = {
  pre: { ja: '発表前', tone: 'var(--event-high)' },
  post: { ja: '発表後', tone: 'var(--event-medium)' },
};
// Crisis-theme radar levels (folded into C.A.O.S. from the old News Radar, v10.192).
const CRISIS_LVL: Record<string, { ja: string; tone: string }> = {
  calm: { ja: '平常', tone: 'var(--text-muted)' },
  elevated: { ja: 'やや増加', tone: 'var(--amber, #fbbf24)' },
  high: { ja: '高水準', tone: 'var(--red, #f87171)' },
};

function hhmm(ts: number | null | undefined): string {
  if (!ts) return '';
  try { return new Date(ts * 1000).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }); }
  catch { return ''; }
}

export const CaosHub: React.FC = () => {
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
  const [intel, setIntel] = React.useState<IntelItem[]>([]);
  const [events, setEvents] = React.useState<CaosEvent[]>([]);
  const { data: newsData } = useMarketNews();
  const { data: evData } = useImportantEvents();   // baseline events so the tier never vanishes
  const { data: dsData } = useDownsideIncidents();  // active drops, surfaced in the hub (v10.178)
  const { data: radarData } = useNewsRadar();       // crisis-theme radar, folded into C.A.O.S. (v10.192)
  const { data: wt } = useWatchtowerStatus();       // watchtower source freshness (v11.5.3)
  const dash = useDashboardEvents();                // v11.4.1: dedupe vs the unified top card

  React.useEffect(() => {
    if (!backend) return;
    let alive = true;
    const base = backend.replace(/\/$/, '');
    const load = () => {
      fetch(`${base}/api/argus/institutional-intelligence`).then((r) => r.json())
        .then((j) => { if (alive) setIntel(j.items || []); }).catch(() => {});
      fetch(`${base}/api/argus/event-analysis`).then((r) => r.json())
        .then((j) => { if (alive) setEvents(j.items || []); }).catch(() => {});
    };
    load();
    const iv = setInterval(load, 5 * 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, [backend]);

  const material = React.useMemo(
    () => intel.filter((it) => it.institutionId &&
      (MATERIAL_TYPES.has(it.contentType || '') || (it.stance && it.stance !== 'neutral'))).slice(0, 3),
    [intel],
  );
  // Events tier (v10.171): ALWAYS show the material upcoming/recent events as a baseline
  // (impact + なぜ重要), and overlay the AI evaluation (概要/事前予想/事後) per eventCode when
  // it has been generated. Previously the tier showed ONLY the AI prose, so it vanished
  // whenever the AI cron hadn't run yet — that's why the event evaluation "disappeared".
  const aiByCode = React.useMemo(() => {
    const m: Record<string, CaosEvent> = {};
    for (const e of events) m[e.eventCode] = e;
    return m;
  }, [events]);
  // v11.4.1: events already shown in the unified top card must NOT be repeated here.
  // When /dashboard-events is live, collapse duplicated scheduled-event narratives into
  // a single "統合済み" note and only render event rows NOT covered by the top card.
  const dashActive = !!(dash && dash.items.length > 0);
  const coveredKeys = React.useMemo(
    () => new Set((dash?.items ?? []).map((it) => it.dedupeKey)),
    [dash],
  );
  const allMaterialEvents = React.useMemo(
    () => (evData?.events ?? [])
      .filter((e) => e.displayImpact === 'critical' || e.displayImpact === 'high')
      .slice(0, 3),
    [evData],
  );
  const materialEvents = React.useMemo(
    () => (dashActive
      ? allMaterialEvents.filter((e) => !coveredKeys.has(dashboardDedupeKey(e.eventCode, e.date)))
      : allMaterialEvents),
    [allMaterialEvents, dashActive, coveredKeys],
  );
  // precision (v10.169): show only market-relevant headlines (drop sports/unrelated
  // noise); fall back to the raw list only if nothing is flagged, so it never empties.
  const allNews = newsData?.items ?? [];
  // v11.5.4 No Stale News: >7-day-old items never render in the hub's news tier
  // (old/stale within 7d stay visible but dimmed as 過去材料).
  const notAncient = allNews.filter((n) => {
    const f = classifyFreshness(n.datetime);
    return f.ageHours == null || f.ageHours <= 7 * 24;
  });
  const relNews = notAncient.filter((n) => n.relevant);
  // v11.5.6 owner rule: newest at the top, older as you go down — always.
  // Undated items sink to the bottom (they must never sit above dated fresh news).
  const news = (relNews.length ? relNews : notAncient)
    .slice()
    .sort((a, b) => {
      const ta = typeof a.datetime === 'number' ? a.datetime : null;
      const tb = typeof b.datetime === 'number' ? b.datetime : null;
      if (ta == null && tb == null) return 0;
      if (ta == null) return 1;
      if (tb == null) return -1;
      return tb - ta;
    })
    .slice(0, 6);
  // v11.5.2: guarantee the on-screen market headlines enter the translation queue
  // (once per session). Never blocks render; never starts translation on the client.
  React.useEffect(() => {
    const pend = news
      .filter((n) => (n.translationStatus === 'pending' || n.translationStatus === 'failed') && n.titleOriginal)
      .map((n) => ({ titleOriginal: String(n.titleOriginal), source: n.source }));
    if (pend.length) autoQueueTranslations('caos-market-news', 'dashboard-events', '', '', pend);
  }, [news]);
  // 急落注視 tier (v10.178): surface the most material active drops in the hub (summary;
  // full per-incident detail stays on the Watchlist page). Sorted critical/high first.
  const SEV_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const incidents = (dsData?.incidents ?? [])
    .filter((i) => i.severity === 'critical' || i.severity === 'high' || i.isHeld)
    .sort((a, b) => (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9))
    .slice(0, 3);
  // Crisis-theme radar (v10.192) — moved INTO C.A.O.S. per the owner. Only shown when
  // the radar has a read (GDELT or the intel-store fallback); one calm line otherwise.
  const crisisThemes = radarData?.status === 'live' ? (radarData.themes ?? []) : [];
  const crisisElevated = crisisThemes.filter((th) => th.level !== 'calm');
  const empty = material.length === 0 && allMaterialEvents.length === 0 && news.length === 0 && incidents.length === 0;
  const hiddenEventCount = dashActive ? allMaterialEvents.length - materialEvents.length : 0;

  // v11.5.3/v11.5.5 Watchtower status line — when did C.A.O.S. last check, patrol
  // liveness (稼働中/遅延/要確認), and per-group newest-item age. Honest, compact.
  const wtLine = (() => {
    if (!wt) return null;
    const cov = wt.coverageByAssetClass || {};
    const ph = wt.patrolHealth;
    const grp = (ac: string, label: string) => {
      const c = cov[ac];
      if (!c || c.newestItemAgeHours == null) return `${label} —`;
      const h = c.newestItemAgeHours;
      return `${label} ${h < 1 ? '1h以内' : h < 24 ? `${Math.floor(h)}h前` : `${Math.floor(h / 24)}d前`}`;
    };
    const checked = (ph?.lastPatrolAt || wt.lastRefreshAt)
      ? String(ph?.lastPatrolAt || wt.lastRefreshAt).slice(11, 16) : '—';
    const lagMin = wt.lastRefreshAt ? (Date.now() - Date.parse(wt.lastRefreshAt)) / 60_000 : null;
    const phStatus = ph?.status;
    const patrolLabel = phStatus === 'healthy' ? '稼働中'
      : phStatus === 'stale' ? '遅延'
      : phStatus === 'degraded' || phStatus === 'error' ? '要確認'
      : phStatus === 'not_ready' ? '起動中' : null;
    const patrolTone = phStatus === 'healthy' ? 'var(--value-positive, #34d399)'
      : phStatus === 'stale' ? 'var(--amber, #fbbf24)'
      : phStatus === 'degraded' || phStatus === 'error' ? 'var(--value-negative, #f87171)'
      : 'var(--text-faint)';
    return {
      text: `C.A.O.S.確認 ${checked}UTC · 最新: ${grp('JP_EQUITY', 'JP')} / ${grp('US_EQUITY', 'US')} / ${grp('CRYPTO_BTC_ETH', '暗号')} / ${grp('FX_USDJPY', '為替')}`,
      patrolLabel, patrolTone,
      note: ph?.status === 'stale' ? 'C.A.O.S.監視が遅延しています'
        : (ph?.deepSweeps24h ?? 0) > 0 ? '急変銘柄を優先巡回中'
        : ph?.baselineOnly ? '現在は基準監視のみ。急変銘柄は検出時に優先巡回します' : null,
      delayed: phStatus === 'stale' || (lagMin != null && lagMin > 45),
      partial: ['GOLD_GLD', 'FX_USDJPY', 'CRYPTO_BTC_ETH'].some((ac) => cov[ac]?.status === 'partial'),
    };
  })();

  return (
    <section className="caoshub">
      <div className="caoshub-head">
        <span className="caoshub-title">C.A.O.S.</span>
        <span className="caoshub-sub">Corroborated Analyst &amp; Official Signals</span>
      </div>
      {wtLine && (
        <p style={{ margin: '2px 0 6px', fontSize: 10.5, color: 'var(--text-faint)' }}>
          {wtLine.patrolLabel && (
            <span style={{ color: wtLine.patrolTone, fontWeight: 600, marginRight: 6 }}>
              巡回{wtLine.patrolLabel}
            </span>
          )}
          {wtLine.text}
          {wtLine.delayed && <span style={{ color: 'var(--amber, #fbbf24)', marginLeft: 6 }}>⚠ ニュース監視に遅延</span>}
          {wtLine.partial && <span style={{ marginLeft: 6 }}>· Gold/FX/Crypto監視はpartial</span>}
          {wtLine.note && !wtLine.delayed && (
            <span style={{ marginLeft: 6 }}>· {wtLine.note}</span>
          )}
        </p>
      )}

      {empty && crisisThemes.length === 0 && (
        <p className="caoshub-empty">機関の見解・公式シグナル・市場ニュースを継続収集しています…</p>
      )}

      {crisisThemes.length > 0 && (
        <div className="caoshub-tier">
          <div className="caoshub-tierhead">
            危機テーマ <span className="caoshub-tiernote">地政学/為替/金融システム/政変/災害 — ブラックスワン監視</span>
          </div>
          {crisisElevated.length > 0 ? crisisElevated.map((th) => (
            <div className="caoshub-crisis" key={th.key}>
              <span className="caoshub-crisis-lvl" style={{ color: (CRISIS_LVL[th.level] ?? CRISIS_LVL.calm).tone }}>
                {(CRISIS_LVL[th.level] ?? CRISIS_LVL.calm).ja}
              </span>
              <span className="caoshub-crisis-label">{th.labelJa}</span>
              <span className="caoshub-crisis-count">{th.count}件</span>
              {th.headlines?.[0] && (
                <a className="caoshub-crisis-head" href={th.headlines[0].url || '#'} target="_blank" rel="noreferrer">
                  {th.headlines[0].title.slice(0, 52)}
                </a>
              )}
            </div>
          )) : (
            <p className="caoshub-crisis-calm">危機テーマは平常。地政学・為替急変・金融システム・政変・災害いずれも顕著な増加なし。</p>
          )}
        </div>
      )}

      {incidents.length > 0 && (
        <div className="caoshub-tier">
          <div className="caoshub-tierhead">急落注視 <span className="caoshub-tiernote">対応は2ページ目のDownside Watchに詳細</span></div>
          {incidents.map((inc) => (
            <div className="caoshub-ds" key={inc.incidentId}>
              <div className="caoshub-ds-l1">
                {inc.isHeld && <span className="caoshub-ds-held">保有</span>}
                <span className="caoshub-ds-sym">{inc.symbol}</span>
                <span className="caoshub-ds-name">{inc.assetName}</span>
                {typeof inc.changePct === 'number' && (
                  <span className="caoshub-ds-chg">{inc.changePct.toFixed(1)}%</span>
                )}
                <span className="caoshub-ds-ovr">{OVERRIDE_LABEL_JA[inc.actionOverride] ?? inc.actionOverride}</span>
              </div>
              <p className="caoshub-ds-reason">{inc.reasonJa}</p>
            </div>
          ))}
        </div>
      )}

      {material.length > 0 && (
        <div className="caoshub-tier">
          <div className="caoshub-tierhead">機関シグナル</div>
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
                {it.titleJa || it.title}
              </a>
            </div>
          ))}
        </div>
      )}

      {(materialEvents.length > 0 || hiddenEventCount > 0) && (
        <div className="caoshub-tier">
          <div className="caoshub-tierhead">
            イベント評価 <span className="caoshub-tiernote">発表前=織り込み/シナリオ · 発表後=結果/受け止め</span>
          </div>
          {/* v11.4.1: scheduled-event analysis lives in the top card now — here we
              only note that it's unified (no duplicated NFP/CPI/FOMC paragraph). */}
          {hiddenEventCount > 0 && (
            <a href="#important-events" className="caose-merged"
               style={{ display: 'block', fontSize: 12, color: 'var(--text-faint)', padding: '2px 0', textDecoration: 'none' }}>
              📎 予定イベント{hiddenEventCount}件の詳細分析はトップのイベントカードに統合済み — 詳細を見る →
            </a>
          )}
          {materialEvents.map((ev) => {
            const ai = aiByCode[ev.eventCode];
            const isPost = ev.daysUntil != null && ev.daysUntil <= 0;
            const ph = isPost ? PHASE.post : PHASE.pre;
            const summary = ai?.summaryJa || ai?.headlineJa || ai?.bodyJa || ev.noviceJa || '';   // AI overlay, else baseline 概要
            const pre = (ai?.preJa || '').trim();
            const post = (ai?.postJa || '').trim();
            return (
              <div className="caose-row" key={ev.eventId}>
                <div className="caose-l1">
                  <span className="caose-phase" style={{ color: ph.tone, borderColor: ph.tone }}>{ph.ja}</span>
                  <span className="caose-code">{ev.eventCode}</span>
                  <span className="caose-impact">影響:{IMPACT_JA[ev.displayImpact] ?? ev.displayImpact}</span>
                </div>
                {summary && (
                  <div className="caose-line"><span className="caose-h">概要</span><span className="caose-t">{summary}</span></div>
                )}
                {/* v11.2.1 (owner request): the 事前予想/事後の答え合わせ rows are ALWAYS
                    visible for their phase — a placeholder shows while the AI hasn't
                    generated yet, so the structure is never reduced to 概要 alone. For
                    POST events the pre-event prediction (preserved by the backend) is
                    shown alongside the answer-check. */}
                {!isPost && (
                  <div className="caose-line"><span className="caose-h caose-h--pre">事前予想(AI)</span>
                    <span className="caose-t" style={pre ? undefined : { color: 'var(--text-faint)' }}>
                      {pre || 'AI生成待ち…（市場の織り込み・大口の構え・サプライズ時のシナリオ）'}
                    </span></div>
                )}
                {isPost && pre && (
                  <div className="caose-line"><span className="caose-h caose-h--pre">事前予想(当時)</span><span className="caose-t">{pre}</span></div>
                )}
                {isPost && (
                  <div className="caose-line"><span className="caose-h caose-h--post">事後の答え合わせ(AI)</span>
                    <span className="caose-t" style={post ? undefined : { color: 'var(--text-faint)' }}>
                      {post || 'AI生成待ち…（結果・事前予想との照合・市場の受け止め）'}
                    </span></div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {news.length > 0 && (
        <div className="caoshub-tier">
          <div className="caoshub-tierhead">
            ニュース <span className="caoshub-tiernote">一般市場ニュース(参考・未検証)</span>
          </div>
          {news.map((it, i) => {
            // v11.5.3: old items render as 過去材料 — never styled as current material
            const fr = classifyFreshness(it.datetime);
            const past = isPastMaterial(fr);
            return (
            <a className="caoshub-news" key={i} href={it.url} target="_blank" rel="noopener noreferrer"
               style={past ? { opacity: 0.55 } : undefined}>
              <div className="caoshub-news-meta">
                {it.major && !past && <span className="caoshub-news-dot" />}
                <span className="caoshub-news-time">{hhmm(it.datetime)}</span>
                <span className="caoshub-news-src">{it.source}</span>
                {past && (
                  <span style={{ fontSize: 9.5, color: 'var(--text-faint)', border: '1px solid var(--line)',
                                 borderRadius: 999, padding: '0 6px' }}>{freshnessLabelJa(fr)}</span>
                )}
                {it.corroboration && CORROB[it.corroboration] && (
                  <span className={`caoshub-corrob ${CORROB[it.corroboration].cls}`}>{CORROB[it.corroboration].ja}</span>
                )}
              </div>
              <div className={`caoshub-news-h${it.major && !past ? ' caoshub-news-h--major' : ''}`}>
                {newsDisplayTitleJa(it)}
              </div>
            </a>
            );
          })}
        </div>
      )}

      <p className="caoshub-foot">
        機関の見解・公式シグナルは建玉ではない・数値は捏造しない。ニュースは参考(未検証)。決定支援のみ。
      </p>
    </section>
  );
};
