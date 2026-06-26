import React from 'react';
import { useMarketNews } from '../../hooks/useMarketNews';
import './CaosEvents.css';
import './MarketInstitutionalSection.css';
import './CaosHub.css';

// C.A.O.S. hub (v10.168) — the single intelligence card on Today, ALWAYS the 2nd card.
// Folds three tiers under one roof: ① 機関シグナル (named-institution views) ② イベント分析
// (概要/事前予想/事後) ③ ニュース (general market headlines). News is always live, so the
// card never disappears (it used to vanish when institutional + event data were both empty).
// Decision-support only; institutional items are reported views (never trades); news is
// uncorroborated context (the same digest is fed to the AI as awareness-only input).

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
const PHASE: Record<string, { ja: string; tone: string }> = {
  pre: { ja: '発表前', tone: 'var(--event-high)' },
  post: { ja: '発表後', tone: 'var(--event-medium)' },
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
  const evShown = events.slice(0, 3);
  // precision (v10.169): show only market-relevant headlines (drop sports/unrelated
  // noise); fall back to the raw list only if nothing is flagged, so it never empties.
  const allNews = newsData?.items ?? [];
  const relNews = allNews.filter((n) => n.relevant);
  const news = (relNews.length ? relNews : allNews).slice(0, 6);
  const empty = material.length === 0 && evShown.length === 0 && news.length === 0;

  return (
    <section className="caoshub">
      <div className="caoshub-head">
        <span className="caoshub-title">C.A.O.S.</span>
        <span className="caoshub-sub">Corroborated Analyst &amp; Official Signals</span>
      </div>

      {empty && (
        <p className="caoshub-empty">機関の見解・公式シグナル・市場ニュースを継続収集しています…</p>
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

      {evShown.length > 0 && (
        <div className="caoshub-tier">
          <div className="caoshub-tierhead">
            イベント分析 <span className="caoshub-tiernote">発表前=織り込み/シナリオ · 発表後=結果/受け止め</span>
          </div>
          {evShown.map((it) => {
            const ph = PHASE[it.phase] ?? PHASE.pre;
            const summary = it.summaryJa || it.headlineJa || it.bodyJa || '';
            const pre = (it.preJa || '').trim();
            const post = (it.postJa || '').trim();
            return (
              <div className="caose-row" key={it.eventId}>
                <div className="caose-l1">
                  <span className="caose-phase" style={{ color: ph.tone, borderColor: ph.tone }}>{ph.ja}</span>
                  <span className="caose-code">{it.eventCode}</span>
                  <span className="caose-impact">影響:{IMPACT_JA[it.displayImpact] ?? it.displayImpact}</span>
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
                {it.tier === 'wire' && <span className="caoshub-news-wire">通信社</span>}
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
