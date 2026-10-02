import React from 'react';
import type { MarketBrief } from '../../lib/marketBrief';
import type { ComparisonPoint } from '../../types/japanMarketComparison';
import { ALERT_HISTORY, TONE_HISTORY, decisionStrip, friendlyEventText, type FeatureRow, type Lean } from '../../lib/todayDecision';
import { useNikkeiLive } from '../../hooks/useJapanMarketComparison';
import './TodayDecisionStrip.css';

const toneLabel = { tail: '材料は追い風寄り', head: '材料は逆風寄り', wait: '材料はまちまち' } as const;
const leanLabel: Record<Lean, string> = { tail: '追い風', head: '逆風', 'soft-head': 'やや逆風', neutral: '中立' };
const alertLabel = { low: '低', normal: '通常', high: '高' } as const;
const momentumLabel = { strong: '強い(過熱気味)', normal: '普通', weak: '弱い(売られすぎ気味)' } as const;
const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
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

/** Conclusion, four numbers and the inputs with their direction, before the detailed explanation. */
export function TodayDecisionStrip({ brief }: { brief: MarketBrief }) {
  const comparison = brief.calculationSnapshots?.['5']?.comparison as { actual?: ComparisonPoint[]; anchorDate?: string } | undefined;
  const strip = decisionStrip(Array.isArray(comparison?.actual) ? comparison!.actual : null, features(brief));
  const headline = brief.unifiedSummary?.sections.view.textJa;
  const live = useNikkeiLive();
  // The delayed intraday value replaces the last close once it is from a later session.
  const lastActual = typeof comparison?.anchorDate === 'string' ? Date.parse(comparison.anchorDate) : NaN;
  const liveCurrent = live && (!Number.isFinite(lastActual) || Date.parse(live.tradedAt) > lastActual + 9 * 3600_000);
  const shownPrice = liveCurrent ? live!.price : strip.close;
  const shownChange = liveCurrent ? live!.changePct : strip.dayChangePct;
  const liveLabel = liveCurrent ? (live!.sessionOpen
    ? `${new Date(live!.tradedAt).toLocaleTimeString('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit' })}時点・約${Math.max(1, Math.round(live!.delaySeconds / 60))}分遅れ`
    : `${new Date(live!.tradedAt).toLocaleDateString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' })} 大引け`) : '前日終値';
  if (strip.close === null && !strip.rows.length) return null;
  return <section className="today-strip" aria-label="今日の結論と数字" data-argus-contract="today-decision-strip-v1">
    {shownPrice !== null && <p className="today-strip__close" data-live={liveCurrent ? 'delayed' : 'close'}>
      <span>日経平均</span><b>{yen(shownPrice)}</b>
      {shownChange !== null && <em className={shownChange >= 0 ? 'is-up' : 'is-down'}>{signed(shownChange)}</em>}
      <small>{liveLabel}</small>
    </p>}
    <div className={`today-strip__verdict is-${strip.tone}`} data-tone={strip.tone}>
      <span className="today-strip__badge">{toneLabel[strip.tone]}</span>
      {headline && <p>{headline}</p>}
      <small className="today-strip__record" data-tone-record={strip.tone}>
        過去の成績({TONE_HISTORY.since}年〜):この判定の5日後に上がったのは{TONE_HISTORY.upAfter[strip.tone]}%。
        どの日でも{TONE_HISTORY.baseUpPct}%なので、方向の予想には使えません。</small>
    </div>
    <div className="today-strip__tiles">
      {strip.alert && <button type="button" className={`today-strip__tile alert-${strip.alert}`} onClick={() => jumpTo('today-nikkei-chart')}>
        <small>急落警戒(5日で-5%以上)</small><b>{alertLabel[strip.alert]}</b>
        <span>過去の同じ段階で{ALERT_HISTORY[strip.alert]}%</span></button>}
      {strip.momentum && <button type="button" className="today-strip__tile" onClick={() => jumpTo('today-nikkei-chart', 'trend')}>
        <small>日経の勢い</small><b>{momentumLabel[strip.momentum]}</b>
        <span>{strip.fiveDayChangePct !== null ? `5日で${signed(strip.fiveDayChangePct)}` : '直近20営業日との比較'}</span></button>}
      {strip.band && <button type="button" className="today-strip__tile" onClick={() => jumpTo('today-nikkei-chart')}>
        <small>5日間の予想値幅(8割)</small><b>{signed(strip.band.lower)}〜{signed(strip.band.upper)}</b>
        <span>{shownPrice !== null ? `${yen(shownPrice * (1 + strip.band.lower / 100))}〜${yen(shownPrice * (1 + strip.band.upper / 100))}円` : ''}</span></button>}
      {brief.chips?.nextEvent && <button type="button" className="today-strip__tile" onClick={() => jumpTo('today-events')}>
        <small>次の山場</small><b className="today-strip__event">{friendlyEventText(brief.chips.nextEvent)}</b></button>}
    </div>
    {strip.rows.length > 0 && <div className="today-strip__rows" aria-label="材料ごとの向き">
      <h2>材料ごとの向き</h2>
      {strip.rows.map(row => <details key={row.id} className="today-strip__row" data-lean={row.lean} data-row={row.id}>
        <summary><span className={`today-strip__chip is-${row.lean}`}>{leanLabel[row.lean]}</span>
          <span><b>{row.title}</b><small>{row.meaning}</small></span></summary>
        <dl><dt>これは何?</dt><dd>{row.what}</dd><dt>今どう?</dt><dd>{row.now}</dd><dt>だから?</dt><dd>{row.soWhat}</dd></dl>
      </details>)}
    </div>}
    <p className="today-strip__note">追い風・逆風は各材料の一般的な読み方で、まとめた判定は過去に5日後の方向を当てていません(上の成績)。急落警戒と値幅は2015〜2026年の実績で確かめた頻度で、将来の確率ではありません。</p>
  </section>;
}
