import { currentLevelMap, type LevelMapState, type LevelMapRecord } from './levelMap';
import type { FutureMapDoc } from '../hooks/useFutureMap';

export type ResearchChart = {
  schemaVersion: 'jp-market-chart-layers-v1'; today: string; start: string; end: string;
  points: Array<{ date: string; close: number; eps: number | null; epsDate: string | null }>;
  current: { morningOf: string; eps: number; epsDate: string; previousClose: number; previousSession: string; atr14: number } | null;
  closePending?: boolean;
  displayMap?: LevelMapRecord & { displayOnly: true; asOf: string; valuationPending: boolean };
  pivots: Array<{ date: string; price: number; kind: 'TOP' | 'BOTTOM'; confirmedOn: string }>;
  pending: { date: string; price: number; kind: 'TOP' | 'BOTTOM'; confirmPrice: number } | null;
  candidates: Array<{ id: string; label: string; start: string; end: string; target: number; stop: number; movingTarget?: boolean }>;
  nearest: Array<{ side: 'UP' | 'DOWN'; multiple: number; price: number; reachedWithin10SessionsPct: number; sessionsMedian: number }>;
  actionAuthority: false; automaticAiCalls: 0;
};
export const dayNumber = (day: string) => Date.parse(`${day}T00:00:00Z`);
const DAY = 86400_000;
export function researchViewport(chart: ResearchChart, days = 90, center = dayNumber(chart.today) + 15 * DAY) {
  const first = dayNumber(chart.start), last = dayNumber(chart.end);
  const size = Math.min(last - first, Math.max(14 * DAY, days * DAY));
  const start = Math.max(first, Math.min(center - size / 2, last - size));
  return { start, end: start + size };
}
/** 拡大の中心にある日付を動かさず、元の日付範囲内で止める。 */
export function zoomResearchViewport(chart: ResearchChart, view: { start: number; end: number }, scale: number, anchor = .5) {
  const fraction = Math.max(0, Math.min(1, anchor));
  const days = Math.min((dayNumber(chart.end) - dayNumber(chart.start)) / DAY,
    Math.max(14, (view.end - view.start) / DAY / Math.max(.1, scale)));
  const at = view.start + fraction * (view.end - view.start);
  return researchViewport(chart, days, at + (.5 - fraction) * days * DAY);
}
/** 拡大しても元の価格・日付を変えない。範囲を端へ移動した時だけ全体の端で止める。 */
export function chartWindow(chart: ResearchChart, recent: boolean, shiftDays = 0) {
  if (!recent) return { start: dayNumber(chart.start), end: dayNumber(chart.end) };
  const size = Math.min(90 * DAY, dayNumber(chart.end) - dayNumber(chart.start));
  const start = Math.max(dayNumber(chart.start), Math.min(dayNumber(chart.today) - 30 * DAY + shiftDays * DAY,
    dayNumber(chart.end) - size));
  return { start, end: start + size };
}
const day = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(dayNumber(v));
const positive = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0;
export function validResearchChart(value: unknown): value is ResearchChart {
  const v = value as ResearchChart | null;
  return !!v && v.schemaVersion === 'jp-market-chart-layers-v1' && v.actionAuthority === false && v.automaticAiCalls === 0
    && day(v.today) && day(v.start) && day(v.end) && v.start < v.today && v.end > v.today
    && Array.isArray(v.points) && v.points.length <= 200 && v.points.every(p => day(p.date) && p.date <= v.today && positive(p.close)
      && (p.eps === null || (positive(p.eps) && day(p.epsDate) && p.epsDate < p.date)))
    && (v.current === null || (day(v.current.morningOf) && v.current.morningOf <= v.today && positive(v.current.eps)
      && day(v.current.epsDate) && v.current.epsDate < v.current.morningOf && positive(v.current.previousClose)))
    && Array.isArray(v.pivots) && v.pivots.every(p => day(p.date) && positive(p.price) && day(p.confirmedOn)
      && p.confirmedOn <= v.today && ['TOP', 'BOTTOM'].includes(p.kind))
    && (v.pending === null || (day(v.pending.date) && positive(v.pending.price) && positive(v.pending.confirmPrice) && ['TOP', 'BOTTOM'].includes(v.pending.kind)))
    && Array.isArray(v.candidates) && v.candidates.every(c => typeof c.id === 'string' && typeof c.label === 'string' && day(c.start) && day(c.end)
      && c.end >= c.start && positive(c.target) && positive(c.stop))
    && Array.isArray(v.nearest) && v.nearest.every(n => ['UP', 'DOWN'].includes(n.side) && positive(n.price) && positive(n.multiple)
      && Number.isFinite(n.reachedWithin10SessionsPct) && n.reachedWithin10SessionsPct >= 0 && n.reachedWithin10SessionsPct <= 100 && Number.isFinite(n.sessionsMedian) && n.sessionsMedian >= 0);
}

export function externalPoints(doc: FutureMapDoc | null, chart: ResearchChart) {
  return (doc?.rows ?? []).filter(r => day(r.start) && day(r.end) && r.end >= r.start && r.level
    && positive(r.level.low) && positive(r.level.high) && r.level.high >= r.level.low)
    .map(r => ({ id: r.id, tag: r.tag, start: r.start, end: r.end,
      at: (dayNumber(r.start) + dayNumber(r.end)) / 2, low: r.level!.low, high: r.level!.high,
      value: (r.level!.low + r.level!.high) / 2 }))
    .filter(r => dayNumber(r.end) >= dayNumber(chart.today) && r.at >= dayNumber(chart.start) && r.at <= dayNumber(chart.end))
    .sort((a, b) => a.at - b.at);
}

/** 欠けたEPSをまたいで線をつながない。 */
export function perSegments(chart: ResearchChart, multiple: number) {
  const points = chart.points.map(p => ({ date: p.date, value: p.eps === null ? null : p.eps * multiple }));
  if (chart.current && chart.current.morningOf > (points.at(-1)?.date ?? ''))
    points.push({ date: chart.current.morningOf, value: chart.current.eps * multiple });
  const segments: Array<Array<{ date: string; value: number }>> = [];
  let segment: Array<{ date: string; value: number }> = [];
  for (const point of points) {
    if (point.value === null) { if (segment.length) segments.push(segment); segment = []; }
    else segment.push({ date: point.date, value: point.value });
  }
  if (segment.length) segments.push(segment);
  return segments;
}

export function displayedChartValuation(chart: ResearchChart) {
  const map = chart.displayMap;
  if (map && currentLevelMap({ schemaVersion: 'jp-market-level-map-state-v1', status: 'AVAILABLE',
    latest: null, chart: { displayMap: map }, morningCount: 0, missedMornings: [],
    score: null, retrospective: null, actionAuthority: false } as LevelMapState) === map
    && map.asOf <= chart.today && map.asOf === chart.points.at(-1)?.date)
    return { eps: map.eps, epsDate: map.epsDate, at: map.asOf };
  return chart.current ? { eps: chart.current.eps, epsDate: chart.current.epsDate, at: chart.current.morningOf } : null;
}

/** 価格の無い見立て。終わっておらず、45日以内の時期だけを時間軸の印にする。 */
export const PERIOD_MARK_MAX_DAYS = 45;
export function externalPeriods(doc: FutureMapDoc | null, chart: ResearchChart) {
  return (doc?.rows ?? []).filter(r => !r.level && !r.past && !r.long && day(r.start) && day(r.end) && r.end >= r.start
    && r.end >= chart.today && r.start <= chart.end && r.end >= chart.start
    && (dayNumber(r.end) - dayNumber(r.start)) / DAY <= PERIOD_MARK_MAX_DAYS)
    .map(r => ({ id: r.id, start: r.start, end: r.end, view: r.view, periodLabel: r.periodLabel || '',
      tag: /^[\s\-―—–]*$/.test(r.tag) ? (r.periodLabel || '') : r.tag }))
    .filter(r => r.tag)
    .sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end));
}

/** 文字と線の重なりを避けるための箱と線分。座標はSVGの値。 */
export type Box = { x1: number; y1: number; x2: number; y2: number };
export type Segment = { x1: number; y1: number; x2: number; y2: number; clip?: boolean };
/** 文字の幅の見積り。数字は約0.62字、全角は1字。少し広めに見る。 */
export function textWidth(text: string, size = 10) {
  let w = 0;
  for (const ch of text) w += /[0-9,.\-+%]/.test(ch) ? .62 : ch === ' ' ? .3 : /[\x21-\x7e]/.test(ch) ? .62 : ch === '·' ? .45 : 1.02;
  return w * size + 2;
}
export function textBox(x: number, y: number, text: string, anchor: 'start' | 'middle' | 'end' = 'start', size = 10): Box {
  const w = textWidth(text, size), x1 = anchor === 'start' ? x : anchor === 'end' ? x - w : x - w / 2;
  return { x1: x1 - 1, y1: y - size - 1, x2: x1 + w + 1, y2: y + size * .3 + 1 };
}
export const boxesOverlap = (a: Box, b: Box) => a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2;
/** 線分が箱を通るか(Liang–Barsky)。 */
export function segmentHitsBox(s: Segment, b: Box) {
  let t0 = 0, t1 = 1;
  const dx = s.x2 - s.x1, dy = s.y2 - s.y1;
  for (const [p, q] of [[-dx, s.x1 - b.x1], [dx, b.x2 - s.x1], [-dy, s.y1 - b.y1], [dy, b.y2 - s.y1]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const t = q / p;
    if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; }
    else { if (t < t0) return false; if (t < t1) t1 = t; }
  }
  return true;
}
/** 置いた文字・線・点を覚え、空いている位置だけを返す。 */
export function labelLayout(plot: Box, segments: Segment[], marks: Box[]) {
  const placed: Box[] = [];
  const clipped = (b: Box): Box | null => {
    const c = { x1: Math.max(b.x1, plot.x1), y1: Math.max(b.y1, plot.y1), x2: Math.min(b.x2, plot.x2), y2: Math.min(b.y2, plot.y2) };
    return c.x1 < c.x2 && c.y1 < c.y2 ? c : null;
  };
  const hitsLine = (b: Box) => {
    const inner = clipped(b);
    return segments.some(s => s.clip ? !!inner && segmentHitsBox(s, inner) : segmentHitsBox(s, b));
  };
  return {
    placed,
    free: (b: Box, within: Box = plot, leader?: Segment) => b.x1 >= within.x1 && b.x2 <= within.x2 && b.y1 >= within.y1 && b.y2 <= within.y2
      && !placed.some(p => boxesOverlap(p, b)) && !marks.some(m => boxesOverlap(m, b)) && !hitsLine(b)
      && (!leader || !placed.some(p => segmentHitsBox(leader, p))),
    place: (b: Box, leader?: Segment) => { placed.push(b); if (leader) segments.push(leader); },
  };
}
