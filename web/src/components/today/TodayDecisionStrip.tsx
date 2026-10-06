import React from 'react';
import type { MarketBrief } from '../../lib/marketBrief';
import type { ComparisonPoint } from '../../types/japanMarketComparison';
import { ALERT_HISTORY, OVERNIGHT_HISTORY, TONE_HISTORY, decisionStrip, friendlyEventText, overnightGap, overnightRecord, type FeatureRow, type Lean } from '../../lib/todayDecision';
import { useNikkeiLive } from '../../hooks/useJapanMarketComparison';
import { marketHeadline } from '../../lib/marketWording';
import './TodayDecisionStrip.css';

const toneLabel = { tail: '材料は追い風寄り', head: '材料は逆風寄り', wait: '材料はまちまち' } as const;
const leanLabel: Record<Lean, string> = { tail: '追い風', head: '逆風', 'soft-head': 'やや逆風', neutral: '中立' };
const alertLabel = { low: '低', normal: '通常', high: '高' } as const;
const momentumLabel = { strong: '上昇・過熱に注意', normal: '通常の範囲', weak: '下落・売られすぎに注意' } as const;
const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
export type CriticalTodayNews = { id: string; title: string; why: string; meta: string };
// Owner request 2026-10-02: each tile opens the part of Today it summarises.
function jumpTo(id: string, openRow?: string) {
  const target = document.getElementById(id);
  if (openRow) {
    const row = document.querySelector<HTMLDetailsElement>(`.today-strip__row[data-row="${openRow}"]`);
    if (row) { row.open = true; row.scrollIntoView({ behavior: 'smooth', block: 'center' }); return; }
  }
  target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
const signed = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;

function features(brief: MarketBrief): FeatureRow[] {
  const snapshot = (brief.calculationSnapshots?.['5'] as { marketFeatureSnapshot?: { features?: unknown } } | undefined)
    ?.marketFeatureSnapshot;
  const rows = Array.isArray(snapshot?.features) ? snapshot.features : [];
  return rows.filter((row): row is FeatureRow => !!row && typeof row.seriesId === 'string'
    && typeof row.date === 'string' && typeof row.value === 'number' && Number.isFinite(row.value));
}

// The last complete inputs on this device. Right after a server restart the
// index research is rebuilt for several minutes and the brief carries no
// numbers; the strip then shows these, labelled, instead of vanishing
// (owner report 2026-10-02: the top of Today disappeared after releases).
const LAST_INPUTS_KEY = 'argus.todayStrip.lastInputs.v1';
type StripInputs = { actual: ComparisonPoint[]; anchorDate?: string; features: FeatureRow[]; savedAt: string };
function readLastInputs(): StripInputs | null {
  try {
    const value = JSON.parse(localStorage.getItem(LAST_INPUTS_KEY) ?? 'null') as StripInputs | null;
    return value && Array.isArray(value.actual) && Array.isArray(value.features) && typeof value.savedAt === 'string' ? value : null;
  } catch { return null; }
}

/** Conclusion, four numbers and the inputs with their direction, before the detailed explanation. */
export function TodayDecisionStrip({ brief, criticalNews = [] }: { brief: MarketBrief; criticalNews?: CriticalTodayNews[] }) {
  const current = brief.calculationSnapshots?.['5']?.comparison as { actual?: ComparisonPoint[]; anchorDate?: string } | undefined;
  const currentFeatures = features(brief);
  const fresh = Array.isArray(current?.actual) && current!.actual.length >= 21;
  React.useEffect(() => {
    if (!fresh) return;
    try {
      localStorage.setItem(LAST_INPUTS_KEY, JSON.stringify({ actual: current!.actual, anchorDate: current!.anchorDate,
        features: currentFeatures, savedAt: new Date().toISOString() }));
    } catch { /* storage unavailable */ }
  }, [fresh, current?.anchorDate, current?.actual?.length]);  // eslint-disable-line react-hooks/exhaustive-deps
  const stored = fresh ? null : readLastInputs();
  const comparison = fresh ? current : stored ? { actual: stored.actual, anchorDate: stored.anchorDate } : undefined;
  const stripActual = Array.isArray(comparison?.actual) ? comparison!.actual : null;
  const stripFeatures = fresh ? currentFeatures : stored?.features ?? [];
  const closeStrip = decisionStrip(stripActual, stripFeatures);
  const headline = marketHeadline(brief.unifiedSummary?.sections.view, brief.unifiedSummary?.sections.reasons);
  const { quote: live, futures } = useNikkeiLive();
  // The delayed intraday value replaces the last close once it is from a later session.
  const lastActual = typeof comparison?.anchorDate === 'string' ? Date.parse(comparison.anchorDate) : NaN;
  const liveTradeAge = live ? Date.now() - Date.parse(live.tradedAt) : NaN;
  const liveReceiptAge = live ? Date.now() - Date.parse(live.receivedAt ?? '') : NaN;
  const liveCurrent = live && (!live.realtime || liveTradeAge >= 0 && liveTradeAge <= 15_000
    && liveReceiptAge >= 0 && liveReceiptAge <= 15_000) && (!Number.isFinite(lastActual) || Date.parse(live.tradedAt) > lastActual + 9 * 3600_000);
  // Owner check 2026-10-03: the overnight future against the close it followed.
  const gap = overnightGap(futures, liveCurrent && !live!.sessionOpen ? live!.price : closeStrip.close,
    liveCurrent ? Date.parse(live!.tradedAt) : lastActual + 6.5 * 3600_000, !!live?.sessionOpen);
  const strip = gap === null ? closeStrip : decisionStrip(stripActual, stripFeatures, gap);
  const gapRecord = strip.overnightGapPct !== null ? overnightRecord(strip.overnightGapPct) : null;
  const shownPrice = liveCurrent ? live!.price : strip.close;
  const shownChange = liveCurrent ? live!.changePct : strip.dayChangePct;
  const liveLabel = liveCurrent ? (live!.sessionOpen
    ? `${new Date(live!.tradedAt).toLocaleTimeString('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit' })}時点・${live!.realtime ? '立花証券 リアルタイム' : `約${Math.max(1, Math.round(live!.delaySeconds / 60))}分遅れ`}`
    : `${new Date(live!.tradedAt).toLocaleDateString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' })} 大引け`) : '前日終値';
  const preparing = !fresh;
  return <section className="today-strip" aria-label="今日の結論と数字" data-argus-contract="today-decision-strip-v1">
    {shownPrice !== null && <p className="today-strip__close" data-live={liveCurrent ? 'delayed' : 'close'}>
      <span>日経平均</span><b>{yen(shownPrice)}</b>
      {shownChange !== null && <em className={shownChange >= 0 ? 'is-up' : 'is-down'}>{signed(shownChange)}</em>}
      <small>{liveLabel}</small>
    </p>}
    {preparing && <p className="today-strip__preparing" role="status">{stored
      ? `サーバーが過去データを準備中のため、${new Date(stored.savedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}時点の数字を表示しています。数分〜20分ほどで最新に戻ります。`
      : 'サーバーが過去データを準備中です。数分〜20分ほどで数字が表示されます。'}</p>}
    <div className={`today-strip__verdict is-${strip.tone}`} data-tone={strip.tone}>
      <span className="today-strip__badge">{toneLabel[strip.tone]}</span>
      {headline && <p>{headline}</p>}
      <small className="today-strip__record" data-tone-record={strip.tone}>
        過去の成績({TONE_HISTORY.since}年〜):この判定の5日後に上がったのは{TONE_HISTORY.upAfter[strip.tone]}%。
        どの日でも{TONE_HISTORY.baseUpPct}%なので、方向の予想には使えません。</small>
      {gapRecord && Math.abs(strip.overnightGapPct!) >= 1 && <p className="today-strip__overnight" data-overnight-gap={strip.overnightGapPct!.toFixed(2)}
        onClick={() => jumpTo('today-nikkei-chart', 'futures')}>
        昨夜の日経先物は終値比<b>{signed(strip.overnightGapPct!)}</b>。{OVERNIGHT_HISTORY.since}年以降、同じ程度の夜のあと5日後に上がっていたのは
        <b>{gapRecord.upPct}%</b>(普段{OVERNIGHT_HISTORY.baseUpPct}%)、5日間の値動きの中央値は{signed(gapRecord.medianPct)}({gapRecord.n}回)。</p>}
    </div>
    <div className="today-strip__tiles">
      {strip.alert && <button type="button" className={`today-strip__tile alert-${strip.alert}`} onClick={() => jumpTo('today-nikkei-chart')}>
        <small>急落警戒(5日で-5%以上)</small><b>{alertLabel[strip.alert]}</b>
        <span>過去の同じ段階で{ALERT_HISTORY[strip.alert]}%</span></button>}
      {strip.momentum && <button type="button" className={`today-strip__tile momentum-${strip.momentum}`} onClick={() => jumpTo('today-nikkei-chart', 'trend')}>
        <small>日経の勢い</small><b>{momentumLabel[strip.momentum]}</b>
        <span>{strip.fiveDayChangePct !== null ? `5日で${signed(strip.fiveDayChangePct)}` : '直近20営業日との比較'}</span></button>}
      {strip.band && <button type="button" className="today-strip__tile tile-range" onClick={() => jumpTo('today-nikkei-chart')}>
        <small>5日間の予想値幅(8割{strip.overnightGapPct !== null ? '・昨夜の先物を反映' : ''})</small><b>{signed(strip.band.lower)}〜{signed(strip.band.upper)}</b>
        <span>{shownPrice !== null ? `${yen(shownPrice * (1 + strip.band.lower / 100))}〜${yen(shownPrice * (1 + strip.band.upper / 100))}円` : ''}</span></button>}
      {criticalNews.length > 0 ? <button type="button" className="today-strip__tile tile-event" onClick={() => jumpTo('today-material-news')}>
        <small>重大ニュース・市場変化 {criticalNews.length}件</small><b className="today-strip__event">{criticalNews[0].title}</b>
        <span>{criticalNews[0].why}</span><span className="today-strip__news-meta">{criticalNews[0].meta}</span>
        <span>詳しく確認する ↓</span>
      </button> : brief.chips?.nextEvent && <button type="button" className="today-strip__tile tile-event" onClick={() => jumpTo('today-events')}>
        <small>次の山場</small><b className="today-strip__event">{friendlyEventText(brief.chips.nextEvent)}</b>
        {/SQ/i.test(brief.chips.nextEvent) && <span>SQ＝先物・オプションの清算<br />前後に株価が大きく上下することも</span>}</button>}
    </div>
    {strip.rows.length > 0 && <div className="today-strip__rows" aria-label="材料ごとの向き">
      <h2>材料ごとの向き</h2>
      {strip.rows.map(row => <details key={row.id} className="today-strip__row" data-lean={row.lean} data-row={row.id}>
        <summary><span className={`today-strip__chip is-${row.lean}`}>{leanLabel[row.lean]}</span>
          <span><b>{row.title}</b><small>{row.meaning}</small></span></summary>
        {row.id === 'trend' ? <p className="today-strip__detail">{row.soWhat}</p> :
          <dl><dt>これは何？</dt><dd>{row.what}</dd><dt>今の状態</dt><dd>{row.now}</dd><dt>見るポイント</dt><dd>{row.soWhat}</dd></dl>}
        {row.id === 'sq' && <a className="today-strip__source" href="https://www.jpx.co.jp/glossary/ta/326.html" target="_blank" rel="noopener noreferrer">SQの仕組みを読む（日本取引所グループ）</a>}
      </details>)}
    </div>}
  </section>;
}
