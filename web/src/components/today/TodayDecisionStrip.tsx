import React from 'react';
import type { MarketBrief } from '../../lib/marketBrief';
import type { ComparisonPoint } from '../../types/japanMarketComparison';
import { ALERT_HISTORY, ALERT_RAISED_HISTORY, MOMENTUM_Z, liveAlertRecord, OVERNIGHT_OPEN_SHARE_PCT, TONE_HISTORY, closeBasisLabel, decisionStrip, friendlyEventText, overnightGap, type FeatureRow, type Lean } from '../../lib/todayDecision';
import { nikkeiLiveCurrent, useJapanMarketComparison, useNikkeiLive } from '../../hooks/useJapanMarketComparison';
import { marketHeadline } from '../../lib/marketWording';
import { MarketPositionCard } from './MarketPositionCard';
import { jumpTo } from '../../lib/todayJump';
import './TodayDecisionStrip.css';

const toneLabel = { tail: '材料は追い風寄り', head: '材料は逆風寄り', wait: '材料はまちまち' } as const;
const leanLabel: Record<Lean, string> = { tail: '追い風', head: '逆風', 'soft-head': 'やや逆風', neutral: '中立' };
// Owner check 2026-10-22: the tile is how likely a further fall is, not how far the market has fallen; say so.
const alertLabel = { low: '起きにくい', normal: '普段並み', high: '起きやすい' } as const;
const momentumLabel = { strong: '上昇・過熱に注意', normal: '通常の範囲', weak: '下落・売られすぎに注意' } as const;
const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
export type CriticalTodayNews = { id: string; title: string; why: string; meta: string };
// Owner request 2026-10-02: each tile opens the part of Today it summarises (shared jumpTo in lib/todayJump).
// Owner decision 2026-10-22: a raised alert carries its own record and count; too few past days are said as such.
const raisedRecord = (r: { pct: number; hits: number; days: number }) => r.days < 20
  ? `直近の下げで一段上げ・過去の例は${r.days}日のみ` : `直近の下げで一段上げ・過去${r.pct}%(${r.days}日中${r.hits}日)`;
// 2026-10-24: the record after release joins the same line once it has 20 scored days.
function alertLine(alert: 'low' | 'normal' | 'high', raised: boolean, recorded: unknown) {
  const isRaised = raised && alert !== 'low';
  const live = liveAlertRecord(recorded, alert, isRaised);
  const past = isRaised ? ALERT_RAISED_HISTORY[alert] : null;
  if (!live) return past ? raisedRecord(past) : `過去の同じ状態で${ALERT_HISTORY[alert]}%`;
  const after = `配信後${live.matured}日中${live.fell}日`;
  if (!past) return `過去${ALERT_HISTORY[alert]}%・${after}`;
  return past.days < 20 ? `一段上げ・${after}` : `一段上げ・過去${past.pct}%・${after}`;
}
const signed = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
// One decimal, or two when rounding would carry the value across the headline's cut point.
const sigmaText = (v: number) => {
  const digits = (Math.abs(Number(v.toFixed(1))) >= MOMENTUM_Z) !== (Math.abs(v) >= MOMENTUM_Z) ? 2 : 1;
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}σ`;
};

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
  const stripAnchor = typeof comparison?.anchorDate === 'string' ? comparison.anchorDate : null;
  const closeStrip = decisionStrip(stripActual, stripFeatures, null, stripAnchor);
  const headline = marketHeadline(brief.unifiedSummary?.sections.view, brief.unifiedSummary?.sections.reasons);
  const { quote: live, futures } = useNikkeiLive();
  const recorded = (useJapanMarketComparison(5).levelMap as unknown as { dropAlert?: unknown } | null | undefined)?.dropAlert;
  // The delayed intraday value replaces the last close once it is from a later session.
  const lastActual = typeof comparison?.anchorDate === 'string' ? Date.parse(comparison.anchorDate) : NaN;
  const liveCurrent = live && nikkeiLiveCurrent(live)
    && (!Number.isFinite(lastActual) || Date.parse(live.tradedAt) > lastActual + 9 * 3600_000);
  // Owner check 2026-10-03: the overnight future against the close it followed.
  const gap = overnightGap(futures, liveCurrent && !live!.sessionOpen ? live!.price : closeStrip.close,
    liveCurrent ? Date.parse(live!.tradedAt) : lastActual + 6.5 * 3600_000, !!live?.sessionOpen);
  const strip = gap === null ? closeStrip : decisionStrip(stripActual, stripFeatures, gap, stripAnchor);
  const shownPrice = liveCurrent ? live!.price : strip.close;
  // Owner request 2026-10-22: the three numbers use the saved closes, not the intraday price; one line under the tiles says which.
  const basis = closeBasisLabel(strip.closeDate);
  const computed = strip.alert !== null || strip.momentum !== null || strip.band !== null;
  // The band's yen line multiplies the shown (possibly delayed intraday) price; the band itself stays close-based.
  const basisNote = basis && computed ? `上の3つは${basis}で計算${strip.band && liveCurrent && shownPrice !== strip.close ? '・値幅の円は現在値で換算' : ''}` : null;
  const shownChange = liveCurrent ? live!.changePct : strip.dayChangePct;
  // Owner policy 2026-10-23: no source or time-precision text beside the price; only a delayed value says so.
  const liveLabel = liveCurrent ? (live!.sessionOpen
    ? (live!.realtime ? null : '遅延')
    : `${new Date(live!.tradedAt).toLocaleDateString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' })} 大引け`) : '前日終値';
  const preparing = !fresh;
  return <section className="today-strip" aria-label="今日の結論と数字" data-argus-contract="today-decision-strip-v1">
    {shownPrice !== null && <p className="today-strip__close" data-live={liveCurrent ? 'delayed' : 'close'}>
      <span>日経平均</span><b>{yen(shownPrice)}</b>
      {shownChange !== null && <em className={shownChange >= 0 ? 'is-up' : 'is-down'}>{signed(shownChange)}</em>}
      {liveLabel && <small>{liveLabel}</small>}
    </p>}
    {preparing && <p className="today-strip__preparing" role="status">{stored
      ? `準備中・${new Date(stored.savedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}時点の数字`
      : '準備中'}</p>}
    <div className={`today-strip__verdict is-${strip.tone}`} data-tone={strip.tone}>
      <span className="today-strip__badge">{toneLabel[strip.tone]}</span>
      {headline && <p>{headline}</p>}
      <small className="today-strip__record" data-tone-record={strip.tone}>
        5日後に上昇 {TONE_HISTORY.upAfter[strip.tone]}%(普段{TONE_HISTORY.baseUpPct}%・{TONE_HISTORY.since}年〜)</small>
      {strip.overnightGapPct !== null && Math.abs(strip.overnightGapPct) >= 1 && <p className="today-strip__overnight" data-overnight-gap={strip.overnightGapPct!.toFixed(2)}
        onClick={() => jumpTo('today-nikkei-chart', 'futures')}>
        昨夜の日経先物 <b>{signed(strip.overnightGapPct!)}</b> · 寄り付きにおよそ{OVERNIGHT_OPEN_SHARE_PCT / 10}割が反映</p>}
    </div>
    <div className="today-strip__tiles">
      <button type="button" className={`today-strip__tile alert-${strip.alert ?? 'pending'}`} onClick={() => jumpTo('today-nikkei-chart')}>
        <small>この先5日の急落(-5%以上)</small><b>{strip.alert ? alertLabel[strip.alert] : '確認中'}</b>
        <span>{strip.alert ? alertLine(strip.alert, strip.alertRaised, recorded) : 'データ待ち'}</span></button>
      <button type="button" className={`today-strip__tile momentum-${strip.momentum ?? 'pending'}`} onClick={() => jumpTo('today-nikkei-chart', 'trend')}>
        <small>日経の勢い</small><b>{strip.momentum ? momentumLabel[strip.momentum] : '確認中'}</b>
        {/* Owner check 2026-10-22: the headline is the distance from the 20-day mean, not the 5-session change. */}
        <span className="today-strip__measure" data-momentum-z={strip.momentumZ !== null ? strip.momentumZ.toFixed(2) : undefined}>
          {strip.momentumZ !== null ? `20日平均${strip.momentumZ < 0 ? 'より下' : strip.momentumZ > 0 ? 'より上' : 'ちょうど'}(${sigmaText(strip.momentumZ)})` : 'データ待ち'}</span></button>
      <button type="button" className="today-strip__tile tile-range" onClick={() => jumpTo('today-nikkei-chart')}>
        <small>5日の値幅(8割{strip.overnightGapPct !== null ? '・先物込み' : ''})</small><b>{strip.band ? `${signed(strip.band.lower)}〜${signed(strip.band.upper)}` : '確認中'}</b>
        <span>{strip.band && shownPrice !== null ? `${yen(shownPrice * (1 + strip.band.lower / 100))}〜${yen(shownPrice * (1 + strip.band.upper / 100))}円` : 'データ待ち'}</span></button>
      {criticalNews.length > 0 ? <button type="button" className="today-strip__tile tile-event" onClick={() => jumpTo('today-material-news')}>
        <small>重大ニュース {criticalNews.length}件</small><b className="today-strip__event">{criticalNews[0].title}</b>
        <span className="today-strip__news-preview">{criticalNews[0].why}</span><span className="today-strip__news-meta">{criticalNews[0].meta}</span>
        <span>詳しく ↓</span>
      </button> : brief.chips?.nextEvent ? <button type="button" className="today-strip__tile tile-event" onClick={() => jumpTo('today-events')}>
        <small>次の山場</small><b className="today-strip__event">{friendlyEventText(brief.chips.nextEvent)}</b></button> : <button type="button" className="today-strip__tile tile-event" onClick={() => jumpTo('today-events')}><small>次の山場</small><b>確認中</b></button>}
    </div>
    {basisNote && <p className="today-strip__basis" data-close-basis={strip.closeDate!}>{basisNote}</p>}
    {/* Owner order 2026-10-20 (docs/TODAY_CARD_ORDER.md 1-4): verdict, the four tiles, then the market position. */}
    <MarketPositionCard brief={brief} />
    {strip.rows.length > 0 && <div className="today-strip__rows" aria-label="材料ごとの向き">
      <h2>材料ごとの向き</h2>
      {strip.rows.map(row => <details key={row.id} className="today-strip__row" data-lean={row.lean} data-row={row.id}>
        <summary><span className={`today-strip__chip is-${row.lean}`}>{leanLabel[row.lean]}</span>
          <span><b>{row.title}</b><small>{row.meaning}</small></span></summary>
        {row.soWhat && <p className="today-strip__detail">{row.soWhat}</p>}
      </details>)}
    </div>}
  </section>;
}
