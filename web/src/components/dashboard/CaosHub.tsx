import React from 'react';
import { useMarketNews } from '../../hooks/useMarketNews';
import { useImportantEvents } from '../../hooks/useImportantEvents';
import { useDownsideIncidents } from '../../hooks/useDownsideIncidents';
import { useNewsRadar } from '../../hooks/useNewsRadar';
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
  const materialEvents = React.useMemo(
    () => (evData?.events ?? [])
      .filter((e) => e.displayImpact === 'critical' || e.displayImpact === 'high')
      .slice(0, 3),
    [evData],
  );
  // precision (v10.169): show only market-relevant headlines (drop sports/unrelated
  // noise); fall back to the raw list only if nothing is flagged, so it never empties.
  const allNews = newsData?.items ?? [];
  const relNews = allNews.filter((n) => n.relevant);
  const news = (relNews.length ? relNews : allNews).slice(0, 6);
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
  const empty = material.length === 0 && materialEvents.length === 0 && news.length === 0 && incidents.length === 0;

  return (
    <section className="caoshub">
      <div className="caoshub-head">
        <span className="caoshub-title">C.A.O.S.</span>
        <span className="caoshub-sub">Corroborated Analyst &amp; Official Signals</span>
      </div>

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

      {materialEvents.length > 0 && (
        <div className="caoshub-tier">
          <div className="caoshub-tierhead">
            イベント評価 <span className="caoshub-tiernote">発表前=織り込み/シナリオ · 発表後=結果/受け止め</span>
          </div>
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
                {pre && (
                  <div className="caose-line"><span className="caose-h caose-h--pre">事前予想</span><span className="caose-t">{pre}</span></div>
                )}
                {post && (
                  <div className="caose-line"><span className="caose-h caose-h--post">事後</span><span className="caose-t">{post}</span></div>
                )}
                {!ai && (
                  <div className="caoshub-pending">AI評価は生成中…(発表前=織り込み・シナリオ / 発表後=結果・大口と市場の受け止め)</div>
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
          {news.map((it, i) => (
            <a className="caoshub-news" key={i} href={it.url} target="_blank" rel="noopener noreferrer">
              <div className="caoshub-news-meta">
                {it.major && <span className="caoshub-news-dot" />}
                <span className="caoshub-news-time">{hhmm(it.datetime)}</span>
                <span className="caoshub-news-src">{it.source}</span>
                {it.corroboration && CORROB[it.corroboration] && (
                  <span className={`caoshub-corrob ${CORROB[it.corroboration].cls}`}>{CORROB[it.corroboration].ja}</span>
                )}
              </div>
              <div className={`caoshub-news-h${it.major ? ' caoshub-news-h--major' : ''}`}>
                {it.headlineJa || it.headline}
              </div>
            </a>
          ))}
        </div>
      )}

      <p className="caoshub-foot">
        機関の見解・公式シグナルは建玉ではない・数値は捏造しない。ニュースは参考(未検証)。決定支援のみ。
      </p>
    </section>
  );
};
