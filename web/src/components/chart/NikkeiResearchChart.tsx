import React, { useEffect, useRef, useState } from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { useFutureMap, type FutureMapDoc } from '../../hooks/useFutureMap';
import { researchViewport, zoomResearchViewport, dayNumber, externalPoints, perSegments, validResearchChart, type ResearchChart } from '../../lib/researchChart';
import './NikkeiResearchChart.css';

const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
const md = (date: string) => `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`;
const multiples = [15, 16, 17, 18, 19, 20, 21];
export function NikkeiResearchChartView({ chart, future }: { chart: ResearchChart; future: FutureMapDoc | null }) {
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
  const last = chart.points.at(-1);
  const window = researchViewport(chart, (viewport.end - viewport.start) / 86400_000, (viewport.start + viewport.end) / 2);
  const recent = window.end - window.start < 100 * 86400_000;
  const inWindow = (date: string) => dayNumber(date) >= window.start && dayNumber(date) <= window.end;
  const visiblePoints = chart.points.filter(p => inWindow(p.date));
  const visibleExternal = external.filter(p => p.at >= window.start && p.at <= window.end);
  const prices = visiblePoints.map(p => p.close);
  if (last) prices.push(last.close);
  const segments = multiples.map(multiple => ({ multiple, segments: perSegments(chart, multiple) }));
  if (layers.per && !recent) segments.forEach(line => line.segments.forEach(s => s.forEach(p => prices.push(p.value))));
  if (layers.per && recent && chart.current) {
    const ratio = chart.current.previousClose / chart.current.eps;
    prices.push(chart.current.eps * Math.floor(ratio), chart.current.eps * Math.ceil(ratio));
  }
  if (layers.external) visibleExternal.forEach(p => prices.push(p.low, p.high));
  if (layers.candidates) chart.candidates.forEach(p => prices.push(p.target, p.stop));
  if (!prices.length) return <p role="status">日経平均の価格履歴を準備しています。</p>;
  const low = Math.min(...prices) * .97, high = Math.max(...prices) * 1.03;
  const top = 30, bottom = enlarged ? 475 : 325, left = 8, right = width - 104;
  const x = (at: number) => left + (at - window.start) / (window.end - window.start) * (right - left);
  const y = (price: number) => bottom - (price - low) / (high - low) * (bottom - top);
  const path = (points: Array<{ date: string; value: number }>) => points.map((p, i) => `${i ? 'L' : 'M'}${x(dayNumber(p.date)).toFixed(2)},${y(p.value).toFixed(2)}`).join(' ');
  const ratio = chart.current ? chart.current.previousClose / chart.current.eps : null;
  const strong = ratio === null ? [] : [...multiples.filter(m => m < ratio).slice(-2), ...multiples.filter(m => m > ratio).slice(0, 2), ...multiples.filter(m => m === ratio)];
  const selectedPoint = visibleExternal.find(p => p.id === selected) ?? visibleExternal[0];
  const close = chart.current?.previousClose ?? last?.close;
  const position = (value: number) => close ? `${value >= close ? '前日終値より上' : '前日終値より下'} ${value >= close ? '+' : ''}${((value / close - 1) * 100).toFixed(1)}%` : '';
  const dateAt = (at: number) => md(new Date(at).toISOString().slice(0, 10));
  const pointLabels = new Map<string, { x: number; y: number }>();
  for (const point of visibleExternal) {
    const lx = Math.max(left + 40, Math.min(right - 40, x(point.at)));
    const slots = [-16, 20, -32, 36, -48, 52, -64, 68].map(offset => y(point.value) + offset)
      .filter(ly => ly >= top + 12 && ly <= bottom - 4);
    const ly = slots.find(ly => ![...pointLabels.values()].some(label => Math.abs(label.x - lx) < 80 && Math.abs(label.y - ly) < 14))
      ?? Math.max(top + 12, Math.min(bottom - 4, y(point.value) - 16));
    pointLabels.set(point.id, { x: lx, y: ly });
  }
  const selectPoint = (point: typeof external[number]) => {
    setSelected(point.id);
    if (point.at < window.start || point.at > window.end)
      setViewport(researchViewport(chart, (window.end - window.start) / 86400_000, point.at));
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
  return <div className="nr-chart" ref={ref} data-argus-contract="nikkei-research-chart-v1">
    <p className="nr-note">日経平均・終値 {last ? `${md(last.date)} ${yen(last.close)}円` : '未取得'}<br />PER線：ARGUS推計（公式値ではない）</p>
    {layers.external && selectedPoint && <div className="nr-selection" aria-live="polite">
      <small>{activePeriod ? 'いま該当する予測期間' : '選んだ予測期間'} · FUTURE MAPの参考予測</small>
      <b>{external.indexOf(selectedPoint) + 1} {selectedPoint.tag} · {md(selectedPoint.start)}〜{md(selectedPoint.end)}</b>
      <p className="nr-selected-price">{selectedPoint.high > selectedPoint.low ? `${yen(selectedPoint.low)}〜${yen(selectedPoint.high)}` : yen(selectedPoint.value)}<span>円</span></p>
      <p>{position(selectedPoint.value)}{selectedPoint.high > selectedPoint.low && '（価格の幅の中央）'}</p>
      <small>この期間の中央に点を置いています。特定の日の到達予想ではありません。予測の成績は未検証です。</small>
    </div>}
    {last && last.date < chart.today && <p className="nr-asof">青線は{md(last.date)}までの終値です。今日{md(chart.today)}の現在値は、この図には含まれていません。</p>}
    <div className="nr-plot-wrap">
    <svg viewBox={`0 0 ${width} ${bottom + 30}`} role="group" aria-label="日経平均の終値と参考予測。左右にドラッグ、2本指で拡大縮小できます。"
      onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerEnd} onPointerCancel={pointerEnd}>
      <defs><clipPath id="nr-plot"><rect x={left} y={top} width={right - left} height={bottom - top} /></clipPath></defs>
      {[0, 1, 2, 3, 4].map(i => { const price = low + (high - low) * i / 4; return <g key={i} className="nr-grid">
        <line x1={left} x2={right} y1={y(price)} y2={y(price)} /><text x={left + 2} y={y(price) - 4}>{yen(price)}</text></g>; })}
      {inWindow(chart.today) && <><line className="nr-today" x1={x(dayNumber(chart.today))} x2={x(dayNumber(chart.today))} y1={top} y2={bottom} />
        <text className="nr-today-label" x={x(dayNumber(chart.today))} y={17} textAnchor="middle">今日 {md(chart.today)}</text></>}
      {close && <><line className="nr-close" x1={left} x2={right} y1={y(close)} y2={y(close)} />
        <text className="nr-close-label" x={left + 3} y={y(close) - 6}>前日終値 {yen(close)}円</text></>}
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
          {pointLabels.has(p.id) && <><line className="nr-point-leader" x1={x(p.at)} y1={y(p.value) - 5} x2={pointLabels.get(p.id)!.x} y2={pointLabels.get(p.id)!.y + 3} />
            <text className="nr-point-label" x={pointLabels.get(p.id)!.x} y={pointLabels.get(p.id)!.y} textAnchor="middle">{i + 1} · {yen(p.value)}円</text></>}
        </g>)}
        {layers.pivots && chart.pivots.map(p => <circle key={`${p.date}-${p.kind}`} className={`nr-pivot ${p.kind === 'TOP' ? 'is-top' : ''}`} cx={x(dayNumber(p.date))} cy={y(p.price)} r={3}>
          <title>{`${md(p.date)} ${p.kind === 'TOP' ? '山' : '谷'}・${md(p.confirmedOn)}に確定`}</title></circle>)}
        {layers.pivots && chart.pending && <circle className="nr-pending" cx={x(dayNumber(chart.pending.date))} cy={y(chart.pending.price)} r={5} />}
      </g>
      {layers.per && chart.current && multiples.filter(m => chart.current!.eps * m >= low && chart.current!.eps * m <= high).map(m => <g key={m} className={`nr-per-label${strong.includes(m) ? ' is-near' : ''}`}>
        <line x1={Math.max(left, Math.min(right, x(dayNumber(chart.current!.morningOf))))} x2={right + 5} y1={y(chart.current!.eps * m)} y2={y(chart.current!.eps * m)} />
        <text x={right + 8} y={y(chart.current!.eps * m) + 3}>PER{m} {yen(chart.current!.eps * m)}円</text></g>)}
      {[window.start, (window.start + window.end) / 2, window.end].map((at, i) => <text className="nr-axis" key={at} x={x(at)} y={bottom + 22}
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
      {layers.external && <span className="nr-key-external">参考予測（未検証）</span>}
      {chart.candidates.length > 0 && <span>検証中の目標・撤回ライン</span>}
      {layers.pivots && <span>確定した高値・安値</span>}</div>
    <details className="nr-guide"><summary>チャートの線と点の意味</summary>
      <p>PER線：企業の利益の何倍の価格かを示す目盛りです。</p>
      <p>白い点線：FUTURE MAPの参考予測です。点は期間と価格の中央で、毎日の予測ではありません。</p>
      <p>目標・撤回ライン：事前に記録した条件の答え合わせに使う線です。実線は目標、点線は想定が崩れる価格です。</p>
      <p>高値・安値の印：終値が4%反転して確定した点です。輪だけの点はまだ未確定です。</p>
    </details>
    {layers.per && <div className="nr-nearest">{chart.nearest.map(n => <article key={n.side} data-side={n.side}>
      <small>{n.side === 'UP' ? '上がった時の目盛り' : '下がった時の目盛り'} · PER{n.multiple}</small>
      <b>{yen(n.price)}<span>円</span></b>
      <p><strong>{n.reachedWithin10SessionsPct}%</strong><span>過去に10営業日以内に届いた割合</span></p>
      <p className="nr-days">到達までの中央値 <b>{n.sessionsMedian}営業日</b></p></article>)}
      {!chart.current && <p>今日のPER水準は未取得です。</p>}
      <small className="nr-nearest-note">過去に届いた頻度です。この線で反発した割合ではありません。日数は到達した事例だけの中央値です。</small></div>}
    {layers.external && <div className="nr-external-list" aria-label="参考予測の期間と価格">
      {external.map((p, i) => <button key={p.id} type="button" aria-pressed={selectedPoint?.id === p.id} onClick={() => selectPoint(p)}>
        {i + 1} {p.tag} · {md(p.start)}{p.end !== p.start ? `〜${md(p.end)}` : ''} · {yen(p.value)}円</button>)}
      {!external.length && <p>{future ? 'この期間に価格付きの参考予測はありません。' : '参考予測を取得できていません。'}</p>}
    </div>}
    {layers.candidates && <div className="nr-notes">{chart.candidates.length ? chart.candidates.map(c => <p key={c.id}>{c.label} · {md(c.start)}〜{md(c.end)} · {c.movingTarget ? '現在の目標（毎朝変動）' : '目標'} {yen(c.target)}円 / 撤回 {yen(c.stop)}円</p>) : <p>表示できる検証用の目標・撤回ラインはありません。</p>}</div>}
    {layers.pivots && chart.pending && <p className="nr-notes">{md(chart.pending.date)}の{chart.pending.kind === 'TOP' ? '山' : '谷'}は未確定。
      終値が{chart.pending.confirmPrice.toLocaleString('ja-JP', { maximumFractionDigits: 2 })}円{chart.pending.kind === 'TOP' ? '以下' : '以上'}で確定します。</p>}
    {layers.per && chart.points.some(p => p.eps === null) && <p className="nr-note">EPSがない日はPER線を途切れさせています。</p>}
    {chart.current && chart.current.morningOf !== chart.today && <p className="nr-note">PERの右端と頻度は{md(chart.current.morningOf)}朝の保存値です。</p>}
  </div>;
}

export function NikkeiResearchChart() {
  const state = useJapanMarketComparison(5);
  const future = useFutureMap();
  const map = state.levelMap as unknown as { chart?: unknown; chartError?: string | null } | null;
  const raw = map?.chart;
  return <div aria-busy={state.loading}>
    {state.error && <p role="status">チャートの更新を確認できません。取得済みの表示には古い値が含まれます。<button type="button" onClick={state.retry}>再取得</button></p>}
    {validResearchChart(raw) ? <NikkeiResearchChartView chart={raw} future={future} /> : <p role="status">{map?.chartError ? 'チャートのデータを作成できませんでした。従来の過去比較は切り替えて確認できます。' : 'チャートの価格・PER履歴を準備しています。'}<button type="button" onClick={state.retry}>再取得</button></p>}
  </div>;
}
