import React, { useEffect, useRef, useState } from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { useFutureMap, type FutureMapDoc } from '../../hooks/useFutureMap';
import { MaterialReactionLine, NoAnalogLine } from './MaterialReactionLine';
import { displayedChartValuation, researchViewport, zoomResearchViewport, dayNumber, externalPoints, externalPeriods, perSegments, validResearchChart,
  labelLayout, textBox, textWidth, type Box, type ResearchChart, type Segment } from '../../lib/researchChart';
import './NikkeiResearchChart.css';

const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
const md = (date: string) => `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`;
const multiples = [15, 16, 17, 18, 19, 20, 21];
const LANE = 19;
type Label = { key: string; className: string; x: number; y: number; anchor: 'start' | 'middle' | 'end'; text: string; leader?: Segment };
type Spot = [number, number, Label['anchor'], Segment?];
export function NikkeiResearchChartView({ chart, future, hasPriceScale=true }: { chart: ResearchChart; future: FutureMapDoc | null; hasPriceScale?:boolean }) {
  const layers = { per: true, external: true, candidates: true, pivots: true };
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(390);
  const [selected, setSelected] = useState<string | null>(null);
  const [viewport, setViewport] = useState(() => researchViewport(chart));
  const [enlarged, setEnlarged] = useState(false);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ view: typeof viewport; x: number; distance: number; fraction: number } | null>(null);
  const dragged = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.round(entry.contentRect.width))));
    observer.observe(el); return () => observer.disconnect();
  }, []);
  const external = externalPoints(future, chart);
  const periods = externalPeriods(future, chart);
  const last = chart.points.at(-1);
  const valuation = displayedChartValuation(chart);
  const window = researchViewport(chart, (viewport.end - viewport.start) / 86400_000, (viewport.start + viewport.end) / 2);
  const recent = window.end - window.start < 100 * 86400_000;
  const inWindow = (date: string) => dayNumber(date) >= window.start && dayNumber(date) <= window.end;
  const visiblePoints = chart.points.filter(p => inWindow(p.date));
  const visibleExternal = external.filter(p => p.at >= window.start && p.at <= window.end);
  const prices = visiblePoints.map(p => p.close);
  if (last) prices.push(last.close);
  const segments = multiples.map(multiple => ({ multiple, segments: perSegments(chart, multiple) }));
  if (layers.per && !recent) segments.forEach(line => line.segments.forEach(s => s.forEach(p => prices.push(p.value))));
  if (layers.per && recent && valuation && last) {
    const ratio = last.close / valuation.eps;
    prices.push(valuation.eps * Math.floor(ratio), valuation.eps * Math.ceil(ratio));
  }
  if (layers.external) visibleExternal.forEach(p => prices.push(p.low, p.high));
  if (layers.candidates) chart.candidates.forEach(p => prices.push(p.target, p.stop));
  if (!prices.length) return <p role="status">日経平均の価格履歴を準備しています。</p>;
  const low = Math.min(...prices) * .97, high = Math.max(...prices) * 1.03;
  const top = 30, bottom = enlarged ? 475 : 325, left = 8, right = width - 104;
  const x = (at: number) => left + (at - window.start) / (window.end - window.start) * (right - left);
  const y = (price: number) => bottom - (price - low) / (high - low) * (bottom - top);
  const path = (points: Array<{ date: string; value: number }>) => points.map((p, i) => `${i ? 'L' : 'M'}${x(dayNumber(p.date)).toFixed(2)},${y(p.value).toFixed(2)}`).join(' ');
  const ratio = valuation && last ? last.close / valuation.eps : null;
  const strong = ratio === null ? [] : [...multiples.filter(m => m < ratio).slice(-2), ...multiples.filter(m => m > ratio).slice(0, 2), ...multiples.filter(m => m === ratio)];
  const visiblePeriods = periods.filter(p => dayNumber(p.end) >= window.start && dayNumber(p.start) <= window.end);
  const selectedPeriod = visiblePeriods.find(p => p.id === selected);
  const selectedPoint = selectedPeriod ? undefined : visibleExternal.find(p => p.id === selected) ?? visibleExternal[0];
  const close = last?.close;
  const closeLabel = last?.date === chart.today ? '当日終値' : '前日終値';
  const position = (value: number) => close ? `${value >= close ? `${closeLabel}より上` : `${closeLabel}より下`} ${value >= close ? '+' : ''}${((value / close - 1) * 100).toFixed(1)}%` : '';
  const dateAt = (at: number) => md(new Date(at).toISOString().slice(0, 10));
  const clampX = (at: number) => Math.max(left, Math.min(right, x(at)));
  // 価格の無い見立ては、時間軸の上に重ならない段で並べる。
  const lanes: number[] = [];
  const periodMarks = visiblePeriods.map(p => {
    const x0 = clampX(dayNumber(p.start)), x1 = Math.max(x0 + 4, clampX(dayNumber(p.end)));
    const w = textWidth(p.tag), tx = Math.max(2, Math.min(x0, width - 4 - w));
    const from = Math.min(x0, tx), to = Math.max(x1, tx + w) + 6;
    let lane = lanes.findIndex(end => end <= from);
    if (lane < 0) { lane = lanes.length; lanes.push(to); } else lanes[lane] = to;
    return { ...p, x0, x1, tx, from, to: to - 6, lane };
  });
  const selectedMark = periodMarks.find(p => p.id === selectedPeriod?.id);
  const laneTop = bottom + 8, axisY = bottom + 22 + lanes.length * LANE, height = axisY + 8;
  // 文字は線・点・ほかの文字に重ならない位置へ置く。置けない時は省く(金額は下の一覧にもある)。
  const plotBox: Box = { x1: left, y1: top, x2: right, y2: bottom };
  const line = (x1: number, y1: number, x2: number, y2: number, clip = false): Segment => ({ x1, y1, x2, y2, clip });
  const polyline = (pts: Array<{ x: number; y: number }>) => pts.slice(1).map((p, i) => line(pts[i].x, pts[i].y, p.x, p.y, true));
  const valuationX = valuation ? clampX(dayNumber(valuation.at)) : right;
  const perLabels = layers.per && valuation ? multiples.filter(m => valuation.eps * m >= low && valuation.eps * m <= high) : [];
  const gridPrices = [0, 1, 2, 3, 4].map(i => low + (high - low) * i / 4);
  const segmentsOut: Segment[] = [
    ...gridPrices.map(price => line(left, y(price), right, y(price))),
    ...(close ? [line(left, y(close), right, y(close))] : []),
    ...(inWindow(chart.today) ? [line(x(dayNumber(chart.today)), top, x(dayNumber(chart.today)), bottom)] : []),
    ...(valuation ? perLabels.map(m => line(valuationX, y(valuation.eps * m), right + 5, y(valuation.eps * m))) : []),
    ...(layers.per ? segments.flatMap(l => l.segments.flatMap(s => polyline(s.map(p => ({ x: x(dayNumber(p.date)), y: y(p.value) }))))) : []),
    ...polyline(chart.points.map(p => ({ x: x(dayNumber(p.date)), y: y(p.close) }))),
    ...(layers.candidates ? chart.candidates.flatMap(c => [c.target, c.stop].map(v => line(x(dayNumber(c.start)), y(v), x(dayNumber(c.end)), y(v), true))) : []),
    ...(layers.external ? polyline(external.map(p => ({ x: x(p.at), y: y(p.value) }))) : []),
  ];
  const dot = (cx: number, cy: number, r: number): Box => ({ x1: cx - r, y1: cy - r, x2: cx + r, y2: cy + r });
  const marks: Box[] = [
    ...(layers.external ? external.map(p => dot(x(p.at), y(p.value), 7)) : []),
    ...(layers.pivots ? chart.pivots.map(p => dot(x(dayNumber(p.date)), y(p.price), 4)) : []),
    ...(layers.pivots && chart.pending ? [dot(x(dayNumber(chart.pending.date)), y(chart.pending.price), 6)] : []),
  ].filter(b => b.x2 > left && b.x1 < right);
  const layout = labelLayout(plotBox, segmentsOut, marks);
  if (inWindow(chart.today)) layout.place(textBox(x(dayNumber(chart.today)), 17, `今日 ${md(chart.today)}`, 'middle'));
  const perTexts = perLabels.map(m => ({ m, text: `PER${m} ${yen(valuation!.eps * m)}円`, y: y(valuation!.eps * m) + 3 }))
    .filter(l => { const b = textBox(right + 8, l.y, l.text, 'start', 9); if (layout.placed.some(p => p.x1 < b.x2 && b.x1 < p.x2 && p.y1 < b.y2 && b.y1 < p.y2)) return false; layout.place(b); return true; });
  const labels: Label[] = [];
  const tryPlace = (key: string, className: string, text: string, options: Spot[], size = 10, within = plotBox) => {
    const found = options.find(([lx, ly, anchor, leader]) => layout.free(textBox(lx, ly, text, anchor, size), within, leader));
    if (!found) return false;
    layout.place(textBox(found[0], found[1], text, found[2], size), found[3]);
    labels.push({ key, className, x: found[0], y: found[1], anchor: found[2], text, leader: found[3] });
    return true;
  };
  if (layers.candidates) chart.candidates.forEach(c => ([['target', '目標', c.target], ['stop', '撤回', c.stop]] as const).forEach(([kind, text, value]) => {
    const xa = clampX(dayNumber(c.start)), xb = clampX(dayNumber(c.end)), ly = y(value);
    if (xb <= xa || ly < top || ly > bottom) return;
    const along: Spot[] = [];
    for (let lx = xb - 24; lx > xa; lx -= 20) along.push([lx, ly - 4, 'end'], [lx, ly + 13, 'end']);
    // 線の近くが混んでいる時は、右端から引き出し線で空いた高さへ出す。
    const callouts: Spot[] = [16, -16, 28, -28, 40, -40, 52, -52, 64, -64].map(dy => [xb + 6, ly + dy + 3.5, 'start', line(xb + 1, ly, xb + 6, ly + dy + (dy > 0 ? -7.5 : 7.5))]);
    tryPlace(`${c.id}-${kind}`, `nr-line-label is-${kind}`, text,
      [[xb + 3, ly + 3.5, 'start'], [xb, ly - 4, 'end'], [xb, ly + 13, 'end'], [xa - 3, ly + 3.5, 'end'], [xa, ly - 4, 'start'], [xa, ly + 13, 'start'], ...along, ...callouts]);
  }));
  const pointLabels = new Map<string, { x: number; y: number; text: string; leader: Segment | null }>();
  const offsets: Array<[number, number]> = [];
  for (let k = 0; k < 12; k++) for (const dy of [-11 - 12 * k, 19 + 12 * k]) for (const dx of [0, -25, 25, -50, 50, -75, 75]) offsets.push([dx, dy]);
  offsets.sort((a, b) => Math.abs(a[1]) + Math.abs(a[0]) * .7 - Math.abs(b[1]) - Math.abs(b[0]) * .7);
  const placePointLabel = (point: typeof external[number], text: string) => {
    const w = textWidth(text), px = x(point.at), py = y(point.value), r = selectedPoint?.id === point.id ? 6 : 4;
    for (const [dx, dy] of offsets) {
      const lx = Math.max(left + w / 2 + 1, Math.min(right - w / 2 - 1, px + dx)), b = textBox(lx, py + dy, text, 'middle');
      const near = Math.abs(lx - px) < w / 2 && Math.abs(dy) < 20;
      const leader = near ? null : line(px, dy < 0 ? py - r - 1 : py + r + 1, Math.max(b.x1 + 2, Math.min(b.x2 - 2, px)), dy < 0 ? b.y2 : b.y1);
      if (!layout.free(b, plotBox, leader ?? undefined)) continue;
      layout.place(b, leader ?? undefined);
      pointLabels.set(point.id, { x: lx, y: py + dy, text, leader });
      return true;
    }
    return false;
  };
  // 金額の入る場所が無い狭い画面では番号だけを置く(金額は下の一覧にある)。
  for (const point of visibleExternal) {
    const n = external.indexOf(point) + 1;
    if (!placePointLabel(point, `${n} · ${yen(point.value)}円`)) placePointLabel(point, String(n));
  }
  if (close) {
    const text = `${closeLabel} ${yen(close)}円`, along: Spot[] = [];
    for (let lx = left + 3; lx + textWidth(text) < right; lx += 16) along.push([lx, y(close) - 5, 'start'], [lx, y(close) + 14, 'start']);
    if (!tryPlace('close', 'nr-close-label', text, [[right + 8, y(close) + 3.5, 'start']], 10, { x1: right, y1: top, x2: width, y2: bottom }))
      tryPlace('close', 'nr-close-label', text, along);
  }
  gridPrices.forEach((price, i) => tryPlace(`grid-${i}`, 'nr-grid-label', yen(price),
    [[left + 2, y(price) - 4, 'start'], [right - 2, y(price) - 4, 'end']], 9, { x1: left, y1: 0, x2: right, y2: bottom }));
  const selectPoint = (point: typeof external[number]) => {
    setSelected(point.id);
    if (point.at < window.start || point.at > window.end)
      setViewport(researchViewport(chart, (window.end - window.start) / 86400_000, point.at));
  };
  const selectPeriod = (period: typeof periods[number]) => {
    setSelected(period.id);
    const at = (dayNumber(period.start) + dayNumber(period.end)) / 2;
    if (dayNumber(period.end) < window.start || dayNumber(period.start) > window.end)
      setViewport(researchViewport(chart, (window.end - window.start) / 86400_000, at));
  };
  const zoom = (scale: number) => setViewport(zoomResearchViewport(chart, window, scale));
  const move = (direction: number) => setViewport(researchViewport(chart,
    (window.end - window.start) / 86400_000, (window.start + window.end) / 2 + direction * (window.end - window.start) / 3));
  const pointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const points = [...pointers.current.values()];
    const middle = points.reduce((n, p) => n + p.x, 0) / points.length;
    const bounds = event.currentTarget.getBoundingClientRect();
    gesture.current = { view: window, x: middle, distance: points.length > 1 ? Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) : 0,
      fraction: Math.max(0, Math.min(1, ((middle - bounds.left) * width / bounds.width - left) / (right - left))) };
    dragged.current = false;
  };
  const pointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!pointers.current.has(event.pointerId) || !gesture.current) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const points = [...pointers.current.values()], initial = gesture.current;
    const middle = points.reduce((n, p) => n + p.x, 0) / points.length;
    const distance = points.length > 1 ? Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) : 0;
    if (Math.abs(middle - initial.x) < 5 && Math.abs(distance - initial.distance) < 5) return;
    dragged.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    const scaled = initial.distance > 0 && distance > 0
      ? zoomResearchViewport(chart, initial.view, distance / initial.distance, initial.fraction) : initial.view;
    const plotWidth = event.currentTarget.getBoundingClientRect().width * (right - left) / width;
    setViewport(researchViewport(chart, (scaled.end - scaled.start) / 86400_000,
      (scaled.start + scaled.end) / 2 - (middle - initial.x) / plotWidth * (scaled.end - scaled.start)));
  };
  const pointerEnd = (event: React.PointerEvent<SVGSVGElement>) => {
    pointers.current.delete(event.pointerId); gesture.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const activePeriod = selectedPoint && selectedPoint.start <= chart.today && selectedPoint.end >= chart.today;
  const periodNow = selectedPeriod && selectedPeriod.start <= chart.today && selectedPeriod.end >= chart.today;
  const periodText = (p: typeof periods[number]) => p.periodLabel || `${md(p.start)}〜${md(p.end)}`;
  return <div className="nr-chart" ref={ref} data-argus-contract="nikkei-research-chart-v1">
    <p className="nr-note">日経平均・終値 {last ? `${md(last.date)} ${yen(last.close)}円` : '未取得'}<br />PER線：決算データから計算したARGUS推計</p>
    {layers.external && selectedPoint && <div className="nr-selection" aria-live="polite">
      <small>{activePeriod ? 'いま該当する予測期間' : '選んだ予測期間'} · FUTURE MAPの参考予測</small>
      <b>{external.indexOf(selectedPoint) + 1} {selectedPoint.tag} · {md(selectedPoint.start)}〜{md(selectedPoint.end)}</b>
      <p className="nr-selected-price">{selectedPoint.high > selectedPoint.low ? `${yen(selectedPoint.low)}〜${yen(selectedPoint.high)}` : yen(selectedPoint.value)}<span>円</span></p>
      <p>{position(selectedPoint.value)}{selectedPoint.high > selectedPoint.low && '（価格の幅の中央）'}</p>
      <small>この期間の中央に点を置いています。特定の日の到達予想ではありません。予測の成績は未検証です。</small>
    </div>}
    {layers.external && selectedPeriod && <div className="nr-selection is-period" aria-live="polite">
      <small>{periodNow ? 'いま該当する時期' : '選んだ時期'} · FUTURE MAPの参考予測</small>
      <b>{selectedPeriod.tag} · {periodText(selectedPeriod)}</b>
      {selectedPeriod.view && <p>{selectedPeriod.view}</p>}
    </div>}
    {last && last.date < chart.today && <p className="nr-asof">{chart.closePending ? `${md(chart.today)}の終値の更新待ちです。取得済みの${md(last.date)}終値を表示しています。` : `青線は${md(last.date)}までの終値です。今日${md(chart.today)}の現在値は、この図には含まれていません。`}</p>}
    <div className="nr-plot-wrap">
    <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label="日経平均の終値と参考予測。左右にドラッグ、2本指で拡大縮小できます。"
      onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerEnd} onPointerCancel={pointerEnd}>
      <defs><clipPath id="nr-plot"><rect x={left} y={top} width={right - left} height={bottom - top} /></clipPath></defs>
      {selectedMark && <rect className="nr-period-band" x={selectedMark.x0} y={top} width={selectedMark.x1 - selectedMark.x0} height={bottom - top} />}
      {gridPrices.map((price, i) => <line key={i} className="nr-grid-line" x1={left} x2={right} y1={y(price)} y2={y(price)} />)}
      {inWindow(chart.today) && <><line className="nr-today" x1={x(dayNumber(chart.today))} x2={x(dayNumber(chart.today))} y1={top} y2={bottom} />
        <text className="nr-today-label" x={x(dayNumber(chart.today))} y={17} textAnchor="middle">今日 {md(chart.today)}</text></>}
      {close && <line className="nr-close" x1={left} x2={right} y1={y(close)} y2={y(close)} />}
      <g clipPath="url(#nr-plot)">
        {layers.per && segments.map(line => <g key={line.multiple} className={`nr-per${strong.includes(line.multiple) ? ' is-near' : ''}`}>
          {line.segments.map((s, i) => <path key={i} d={path(s)} />)}</g>)}
        <path className="nr-price" d={path(chart.points.map(p => ({ date: p.date, value: p.close })))} />
        {layers.candidates && chart.candidates.map(c => <g key={c.id}>
          <line className="nr-target" x1={x(dayNumber(c.start))} x2={x(dayNumber(c.end))} y1={y(c.target)} y2={y(c.target)} />
          <line className="nr-stop" x1={x(dayNumber(c.start))} x2={x(dayNumber(c.end))} y1={y(c.stop)} y2={y(c.stop)} />
        </g>)}
        {layers.external && <path className="nr-external" d={external.map((p, i) => `${i ? 'L' : 'M'}${x(p.at)},${y(p.value)}`).join(' ')} />}
        {layers.external && external.map((p, i) => <g key={p.id} role="button" tabIndex={p.at >= window.start && p.at <= window.end ? 0 : -1}
          aria-label={`${i + 1} ${p.tag}、${md(p.start)}から${md(p.end)}、${yen(p.value)}円、${position(p.value)}`}
          aria-pressed={selectedPoint?.id === p.id} onClick={() => { if (!dragged.current) selectPoint(p); }} onKeyDown={event => {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectPoint(p); }
          }}>
          {p.high > p.low && <rect className="nr-band" x={x(Math.max(dayNumber(p.start), dayNumber(chart.today)))}
            y={y(p.high)} width={Math.max(3, x(Math.min(dayNumber(p.end), dayNumber(chart.end))) - x(Math.max(dayNumber(p.start), dayNumber(chart.today))))} height={Math.max(2, y(p.low) - y(p.high))} />}
          <circle className="nr-point-hit" cx={x(p.at)} cy={y(p.value)} r={18} />
          <circle className="nr-point" cx={x(p.at)} cy={y(p.value)} r={selectedPoint?.id === p.id ? 6 : 4}><title>{`${i + 1} ${p.tag} ${md(p.start)}〜${md(p.end)} ${yen(p.value)}円`}</title></circle>
          {pointLabels.has(p.id) && <>{pointLabels.get(p.id)!.leader && <line className="nr-point-leader" x1={pointLabels.get(p.id)!.leader!.x1} y1={pointLabels.get(p.id)!.leader!.y1}
            x2={pointLabels.get(p.id)!.leader!.x2} y2={pointLabels.get(p.id)!.leader!.y2} />}
            <text className="nr-point-label" x={pointLabels.get(p.id)!.x} y={pointLabels.get(p.id)!.y} textAnchor="middle">{pointLabels.get(p.id)!.text}</text></>}
        </g>)}
        {layers.pivots && chart.pivots.map(p => <circle key={`${p.date}-${p.kind}`} className={`nr-pivot ${p.kind === 'TOP' ? 'is-top' : ''}`} cx={x(dayNumber(p.date))} cy={y(p.price)} r={3}>
          <title>{`${md(p.date)} ${p.kind === 'TOP' ? '山' : '谷'}・${md(p.confirmedOn)}に確定`}</title></circle>)}
        {layers.pivots && chart.pending && <circle className="nr-pending" cx={x(dayNumber(chart.pending.date))} cy={y(chart.pending.price)} r={5} />}
      </g>
      {perTexts.length > 0 && <g className="nr-per-lines">{perLabels.map(m => <line key={m} className={`nr-per-guide${strong.includes(m) ? ' is-near' : ''}`}
        x1={valuationX} x2={right + 5} y1={y(valuation!.eps * m)} y2={y(valuation!.eps * m)} />)}</g>}
      {perTexts.map(l => <text key={l.m} className={`nr-per-text${strong.includes(l.m) ? ' is-near' : ''}`} x={right + 8} y={l.y}>{l.text}</text>)}
      {labels.map(l => <React.Fragment key={l.key}>{l.leader && <line className={`nr-label-leader${l.className.includes('is-stop') ? ' is-stop' : l.className.includes('is-target') ? ' is-target' : ''}`} x1={l.leader.x1} y1={l.leader.y1} x2={l.leader.x2} y2={l.leader.y2} />}
        <text className={l.className} x={l.x} y={l.y} textAnchor={l.anchor}>{l.text}</text></React.Fragment>)}
      {periodMarks.map(p => <g key={p.id} className="nr-period" role="button" tabIndex={0} aria-pressed={selectedPeriod?.id === p.id}
        aria-label={`${p.tag}、${periodText(p)}`} onClick={() => { if (!dragged.current) selectPeriod(p); }}
        onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectPeriod(p); } }}>
        <rect className="nr-period-hit" x={p.from - 2} y={laneTop + p.lane * LANE - 3} width={p.to - p.from + 4} height={LANE} />
        <rect className="nr-period-bar" x={p.x0} y={laneTop + p.lane * LANE} width={p.x1 - p.x0} height={3} rx={1.5} />
        <text className="nr-period-tag" x={p.tx} y={laneTop + p.lane * LANE + 14}>{p.tag}</text>
      </g>)}
      {[window.start, (window.start + window.end) / 2, window.end].map((at, i) => <text className="nr-axis" key={at} x={x(at)} y={axisY}
        textAnchor={i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}>{dateAt(at)}</text>)}
    </svg>
    <div className="nr-controls nr-zoom" role="group" aria-label="チャートの拡大と期間移動">
      <button type="button" aria-label="過去へ移動" disabled={window.start <= dayNumber(chart.start)} onClick={() => move(-1)}>←</button>
      <button type="button" aria-label="縮小" onClick={() => zoom(1 / 1.5)}>−</button>
      <button type="button" onClick={() => { setViewport(researchViewport(chart)); setSelected(null); }}>今日へ戻る</button>
      <button type="button" aria-label="拡大" onClick={() => zoom(1.5)}>＋</button>
      <button type="button" aria-label="未来へ移動" disabled={window.end >= dayNumber(chart.end)} onClick={() => move(1)}>→</button>
      <button type="button" aria-label="チャートを縦に拡大" aria-pressed={enlarged} onClick={() => setEnlarged(v => !v)}>↕</button>
    </div>
    <p className="nr-gesture-note">左右に動かす · 2本指で拡大・縮小</p>
    </div>
    <div className="nr-legend"><span className="nr-key-price">日経平均・終値</span>{layers.per && <span className="nr-key-per">PER15〜21</span>}
      {layers.external && <span className="nr-key-external">参考予測</span>}
      {chart.candidates.length > 0 && <><span className="nr-key-target">目標</span><span className="nr-key-stop">撤回</span></>}
      {layers.pivots && <span>確定した高値・安値</span>}</div>
    <details className="nr-guide"><summary>チャートの線と点の意味</summary>
      <p>PER線：取得した構成銘柄の決算データから推計したEPSに、倍率を掛けた価格です。</p>
      <p>日経の公式PERは公開されています。公式は日経の予想利益、ARGUSは取得した決算データを使うため、値は一致するとは限りません。今の線は公式PERから引いた線ではありません。</p>
      <p>白い点線：FUTURE MAPの参考予測です。点は期間と価格の中央で、毎日の予測ではありません。</p>
      <p>目標・撤回ライン：事前に記録した条件の答え合わせに使う線です。実線は目標、点線は想定が崩れる価格です。</p>
      <p>高値・安値の印：終値が4%反転して確定した点です。輪だけの点はまだ未確定です。</p>
    </details>
    {layers.per && hasPriceScale && <p className="nr-price-scale-link"><a href="#today-price-scale">上・下のPER価格までの距離と、過去の到達割合を見る ↓</a></p>}
    {layers.external && <div className="nr-external-list" aria-label="参考予測の期間と価格">
      {external.map((p, i) => <button key={p.id} type="button" aria-pressed={selectedPoint?.id === p.id} onClick={() => selectPoint(p)}>
        {i + 1} {p.tag} · {md(p.start)}{p.end !== p.start ? `〜${md(p.end)}` : ''} · {yen(p.value)}円</button>)}
      {!external.length && <p>{future ? 'この期間に価格付きの参考予測はありません。' : '参考予測を取得できていません。'}</p>}
    </div>}
    {layers.candidates && <div className="nr-notes">{chart.candidates.length ? chart.candidates.map(c => <p key={c.id}>{c.label} · {md(c.start)}〜{md(c.end)} · {c.movingTarget ? '現在の目標（毎朝変動）' : '目標'} {yen(c.target)}円 / 撤回 {yen(c.stop)}円</p>) : <p>表示できる検証用の目標・撤回ラインはありません。</p>}</div>}
    {layers.pivots && chart.pending && <p className="nr-notes">{md(chart.pending.date)}の{chart.pending.kind === 'TOP' ? '山' : '谷'}は未確定。
      終値が{chart.pending.confirmPrice.toLocaleString('ja-JP', { maximumFractionDigits: 2 })}円{chart.pending.kind === 'TOP' ? '以下' : '以上'}で確定します。</p>}
    {layers.per && chart.points.some(p => p.eps === null) && <p className="nr-note">EPSがない日はPER線を途切れさせています。</p>}
    {valuation && <p className="nr-note">PERの右端は{md(valuation.epsDate)}の推計EPSから計算。{last && valuation.epsDate < last.date ? '当日分のPER入力は更新待ちです。' : ''}</p>}
    {chart.current && !chart.displayMap && chart.current.morningOf !== chart.today && <p className="nr-note">PERの右端と頻度は{md(chart.current.morningOf)}朝の保存値です。</p>}
  </div>;
}

export function NikkeiResearchChart() {
  const state = useJapanMarketComparison(5);
  const future = useFutureMap();
  const map = state.levelMap as unknown as { chart?: unknown; chartError?: string | null } | null;
  const raw = map?.chart;
  return <div aria-busy={state.loading}>
    {state.levelMapError && <p role="status">チャートの更新を確認できません。取得済みの表示には古い値が含まれます。<button type="button" onClick={state.retry}>再取得</button></p>}
    {validResearchChart(raw) ? <NikkeiResearchChartView chart={raw} future={future} hasPriceScale={!!state.levelMap?.latest} /> : <p role="status">{map?.chartError ? 'チャートのデータを作成できませんでした。従来の過去比較は切り替えて確認できます。' : 'チャートの価格・PER履歴を準備しています。'}<button type="button" onClick={state.retry}>再取得</button></p>}
    <NoAnalogLine document={state.document} />
    <MaterialReactionLine research={state.document?.forecast.materialReactionResearch} />
  </div>;
}
