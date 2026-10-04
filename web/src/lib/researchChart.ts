import type { FutureMapDoc } from '../hooks/useFutureMap';

export type ResearchChart = {
  schemaVersion: 'jp-market-chart-layers-v1'; today: string; start: string; end: string;
  points: Array<{ date: string; close: number; eps: number | null; epsDate: string | null }>;
  current: { morningOf: string; eps: number; epsDate: string; previousClose: number; previousSession: string; atr14: number } | null;
  pivots: Array<{ date: string; price: number; kind: 'TOP' | 'BOTTOM'; confirmedOn: string }>;
  pending: { date: string; price: number; kind: 'TOP' | 'BOTTOM'; confirmPrice: number } | null;
  candidates: Array<{ id: string; label: string; start: string; end: string; target: number; stop: number; movingTarget?: boolean }>;
  nearest: Array<{ side: 'UP' | 'DOWN'; multiple: number; price: number; reachedWithin10SessionsPct: number; sessionsMedian: number }>;
  actionAuthority: false; automaticAiCalls: 0;
};
export const dayNumber = (day: string) => Date.parse(`${day}T00:00:00Z`);
const DAY = 86400_000;
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
    .filter(r => r.at > dayNumber(chart.today) && r.at <= dayNumber(chart.end))
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
