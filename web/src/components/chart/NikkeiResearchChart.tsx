import React, { useEffect, useRef, useState } from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { useFutureMap, type FutureMapDoc } from '../../hooks/useFutureMap';
import { chartWindow, dayNumber, externalPoints, perSegments, validResearchChart, type ResearchChart } from '../../lib/researchChart';
import './NikkeiResearchChart.css';

const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
const md = (date: string) => `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`;
const multiples = [15, 16, 17, 18, 19, 20, 21];
export function NikkeiResearchChartView({ chart, future }: { chart: ResearchChart; future: FutureMapDoc | null }) {
  const [layers, setLayers] = useState({ per: true, external: true, candidates: false, pivots: false });
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(390);
  const [selected, setSelected] = useState<string | null>(null);
  const [recent, setRecent] = useState(true);
  const [shift, setShift] = useState(0);
  const [enlarged, setEnlarged] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(320, Math.round(entry.contentRect.width))));
    observer.observe(el); return () => observer.disconnect();
  }, []);
  const external = externalPoints(future, chart);
  const last = chart.points.at(-1);
  const window = chartWindow(chart, recent, shift);
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
  const selectedPoint = external.find(p => p.id === selected) ?? visibleExternal[0];
  const close = chart.current?.previousClose ?? last?.close;
  const position = (value: number) => close ? `${value >= close ? '前日終値より上' : '前日終値より下'} ${value >= close ? '+' : ''}${((value / close - 1) * 100).toFixed(1)}%` : '';
  const dateAt = (at: number) => md(new Date(at).toISOString().slice(0, 10));
  const selectPoint = (point: typeof external[number]) => {
    setSelected(point.id);
    if (recent && (point.at < window.start || point.at > window.end))
      setShift((point.at - dayNumber(chart.today)) / 86400_000 - 15);
  };
  return <div className="nr-chart" ref={ref} data-argus-contract="nikkei-research-chart-v1">
    <div className="nr-controls nr-zoom" role="group" aria-label="チャートの拡大と期間移動">
      <button type="button" aria-pressed={recent} onClick={() => { setRecent(true); setShift(0); }}>直近を拡大</button>
      <button type="button" aria-pressed={!recent} onClick={() => { setRecent(false); setShift(0); }}>半年の全体</button>
      <button type="button" aria-pressed={enlarged} onClick={() => setEnlarged(v => !v)}>縦に拡大</button>
      {recent && <><button type="button" disabled={window.start <= dayNumber(chart.start)} onClick={() => setShift(v => v - 30)}>← 過去へ</button>
        <button type="button" disabled={window.end >= dayNumber(chart.end)} onClick={() => setShift(v => v + 30)}>先の期間へ →</button></>}
    </div>
    <div className="nr-controls" role="group" aria-label="チャートに重ねる情報">
      {([['per', 'PER線'], ['external', '外部の見立て'], ['candidates', '記録中の候補'], ['pivots', '山・谷']] as const).map(([id, label]) =>
        <button key={id} type="button" aria-pressed={layers[id]} onClick={() => setLayers(v => ({ ...v, [id]: !v[id] }))}>{label}</button>)}
    </div>
    <details className="nr-guide"><summary>線・点・切り替えの意味</summary>
      <p>PER線：企業の利益の何倍の価格かを示す目盛りです。</p>
      <p>外部の見立て：FUTURE MAPに記録された将来の時期と価格。白い点線はその点をつないでいます。</p>
      <p>記録中の候補：事前に条件を決め、結果を確かめている候補。目標と、想定が崩れる価格を表示します。</p>
      <p>山・谷：過去の終値が4%反転して確定した高値・安値です。未確定の点は輪で表示します。</p>
      <p>切り替えは、一つの情報を詳しく読むために線を減らすものです。点や線が重なった時に使います。</p>
    </details>
    <p className="nr-note">日経平均・終値 {last ? `${md(last.date)} ${yen(last.close)}円` : '未取得'}<br />PER線：ARGUS推計（公式値ではない）</p>
    {layers.external && selectedPoint && <div className="nr-selection" aria-live="polite">
      <b>{external.indexOf(selectedPoint) + 1} {selectedPoint.tag} · {md(selectedPoint.start)}〜{md(selectedPoint.end)}</b>
      <p>{yen(selectedPoint.value)}円 · {position(selectedPoint.value)}</p>
      <small>この期間の中央に点を置いています。明日の予測ではありません。{selectedPoint.high > selectedPoint.low ? `価格の幅：${yen(selectedPoint.low)}〜${yen(selectedPoint.high)}円。` : ''}</small>
    </div>}
    <svg viewBox={`0 0 ${width} ${bottom + 30}`} role="group" aria-label="日経平均の価格とPER線、外部の見立て。点を選んで期間と価格を確認できます。">
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
          aria-pressed={selectedPoint?.id === p.id} onClick={() => selectPoint(p)} onKeyDown={event => {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectPoint(p); }
          }}>
          {p.high > p.low && <rect className="nr-band" x={x(Math.max(dayNumber(p.start), dayNumber(chart.today)))}
            y={y(p.high)} width={Math.max(3, x(Math.min(dayNumber(p.end), dayNumber(chart.end))) - x(Math.max(dayNumber(p.start), dayNumber(chart.today))))} height={Math.max(2, y(p.low) - y(p.high))} />}
          <circle className="nr-point-hit" cx={x(p.at)} cy={y(p.value)} r={18} />
          <circle className="nr-point" cx={x(p.at)} cy={y(p.value)} r={selectedPoint?.id === p.id ? 6 : 4}><title>{`${i + 1} ${p.tag} ${md(p.start)}〜${md(p.end)} ${yen(p.value)}円`}</title></circle>
          <text className="nr-point-label" x={x(p.at)} y={y(p.value) - (i % 2 ? 25 : 12)} textAnchor="middle">{i + 1} · {dateAt(p.at)}</text>
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
    <div className="nr-legend"><span className="nr-key-price">日経平均・終値</span>{layers.per && <span className="nr-key-per">PER15〜21</span>}
      {layers.external && <span className="nr-key-external">外部の見立て（未検証）</span>}
      {layers.candidates && <span>候補（未検証）：実線＝目標、点線＝崩れ</span>}
      {layers.pivots && <span>山・谷：終値が4%反転して確定</span>}</div>
    {layers.per && <div className="nr-nearest">{chart.nearest.map(n => <p key={n.side}>
      {n.side === 'UP' ? '一つ上' : '一つ下'}のPER{n.multiple}：{yen(n.price)}円<br />
      <small>10営業日以内に届いた過去の頻度 {n.reachedWithin10SessionsPct}% · 日数の中央値 {n.sessionsMedian}営業日</small></p>)}
      {!chart.current && <p>今日のPER水準は未取得です。</p>}
      <small>日数は到達した事例の中央値。PER線で反発する頻度ではありません。</small></div>}
    {layers.external && <div className="nr-external-list" aria-label="外部の見立ての点">
      {external.map((p, i) => <button key={p.id} type="button" aria-pressed={selectedPoint?.id === p.id} onClick={() => selectPoint(p)}>
        {i + 1} {p.tag} · {md(p.start)}{p.end !== p.start ? `〜${md(p.end)}` : ''} · {yen(p.value)}円</button>)}
      {!external.length && <p>{future ? 'この期間に水準付きの見立てはありません。' : '外部の見立てを取得できていません。'}</p>}
    </div>}
    {layers.candidates && <div className="nr-notes">{chart.candidates.length ? chart.candidates.map(c => <p key={c.id}>{c.label} · {md(c.start)}〜{md(c.end)} · {c.movingTarget ? '現在の目標（毎朝変動）' : '目標'} {yen(c.target)}円 / 崩れ {yen(c.stop)}円</p>) : <p>目標と崩れの水準が確定した、記録中の候補はありません。</p>}</div>}
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
