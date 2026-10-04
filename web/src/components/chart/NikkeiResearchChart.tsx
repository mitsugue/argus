import React, { useEffect, useRef, useState } from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { useFutureMap, type FutureMapDoc } from '../../hooks/useFutureMap';
import { dayNumber, externalPoints, perSegments, validResearchChart, type ResearchChart } from '../../lib/researchChart';
import './NikkeiResearchChart.css';

const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
const md = (date: string) => `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`;
const multiples = [15, 16, 17, 18, 19, 20, 21];
export function NikkeiResearchChartView({ chart, future }: { chart: ResearchChart; future: FutureMapDoc | null }) {
  const [layers, setLayers] = useState({ per: true, external: true, candidates: false, pivots: false });
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(390);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(320, Math.round(entry.contentRect.width))));
    observer.observe(el); return () => observer.disconnect();
  }, []);
  const external = externalPoints(future, chart);
  const last = chart.points.at(-1);
  const prices = chart.points.map(p => p.close);
  const segments = multiples.map(multiple => ({ multiple, segments: perSegments(chart, multiple) }));
  if (layers.per) segments.forEach(line => line.segments.forEach(s => s.forEach(p => prices.push(p.value))));
  if (layers.external) external.forEach(p => prices.push(p.low, p.high));
  if (layers.candidates) chart.candidates.forEach(p => prices.push(p.target, p.stop));
  if (!prices.length) return <p role="status">日経平均の価格履歴を準備しています。</p>;
  const low = Math.min(...prices) * .97, high = Math.max(...prices) * 1.03;
  const top = 30, bottom = 325, left = 8, right = width - 104;
  const x = (at: number) => left + (at - dayNumber(chart.start)) / (dayNumber(chart.end) - dayNumber(chart.start)) * (right - left);
  const y = (price: number) => bottom - (price - low) / (high - low) * (bottom - top);
  const path = (points: Array<{ date: string; value: number }>) => points.map((p, i) => `${i ? 'L' : 'M'}${x(dayNumber(p.date)).toFixed(2)},${y(p.value).toFixed(2)}`).join(' ');
  const ratio = chart.current ? chart.current.previousClose / chart.current.eps : null;
  const strong = ratio === null ? [] : [...multiples.filter(m => m < ratio).slice(-2), ...multiples.filter(m => m > ratio).slice(0, 2), ...multiples.filter(m => m === ratio)];
  const selectedPoint = external.find(p => p.id === selected);
  return <div className="nr-chart" ref={ref} data-argus-contract="nikkei-research-chart-v1">
    <div className="nr-controls" role="group" aria-label="チャートに重ねる情報">
      {([['per', 'PER線'], ['external', '外部の見立て'], ['candidates', '記録中の候補'], ['pivots', '山・谷']] as const).map(([id, label]) =>
        <button key={id} type="button" aria-pressed={layers[id]} onClick={() => setLayers(v => ({ ...v, [id]: !v[id] }))}>{label}</button>)}
    </div>
    <p className="nr-note">日経平均・終値 {last ? `${md(last.date)} ${yen(last.close)}円` : '未取得'}<br />PER線：ARGUS推計（公式値ではない）</p>
    <svg viewBox={`0 0 ${width} 354`} role="img" aria-label="過去約6か月の日経平均とPER線、今後約3か月の外部の見立て">
      <defs><clipPath id="nr-plot"><rect x={left} y={top} width={right - left} height={bottom - top} /></clipPath></defs>
      {[0, 1, 2, 3, 4].map(i => { const price = low + (high - low) * i / 4; return <g key={i} className="nr-grid">
        <line x1={left} x2={right} y1={y(price)} y2={y(price)} /><text x={left + 2} y={y(price) - 4}>{yen(price)}</text></g>; })}
      <line className="nr-today" x1={x(dayNumber(chart.today))} x2={x(dayNumber(chart.today))} y1={top} y2={bottom} />
      <text className="nr-today-label" x={x(dayNumber(chart.today))} y={17} textAnchor="middle">今日 {md(chart.today)}</text>
      <g clipPath="url(#nr-plot)">
        {layers.per && segments.map(line => <g key={line.multiple} className={`nr-per${strong.includes(line.multiple) ? ' is-near' : ''}`}>
          {line.segments.map((s, i) => <path key={i} d={path(s)} />)}</g>)}
        <path className="nr-price" d={path(chart.points.map(p => ({ date: p.date, value: p.close })))} />
        {layers.candidates && chart.candidates.map(c => <g key={c.id}>
          <line className="nr-target" x1={x(dayNumber(c.start))} x2={x(dayNumber(c.end))} y1={y(c.target)} y2={y(c.target)} />
          <line className="nr-stop" x1={x(dayNumber(c.start))} x2={x(dayNumber(c.end))} y1={y(c.stop)} y2={y(c.stop)} />
        </g>)}
        {layers.external && <path className="nr-external" d={external.map((p, i) => `${i ? 'L' : 'M'}${x(p.at)},${y(p.value)}`).join(' ')} />}
        {layers.external && external.map((p, i) => <g key={p.id}>
          {p.high > p.low && <rect className="nr-band" x={x(Math.max(dayNumber(p.start), dayNumber(chart.today)))}
            y={y(p.high)} width={Math.max(3, x(Math.min(dayNumber(p.end), dayNumber(chart.end))) - x(Math.max(dayNumber(p.start), dayNumber(chart.today))))} height={Math.max(2, y(p.low) - y(p.high))} />}
          <circle className="nr-point" cx={x(p.at)} cy={y(p.value)} r={4}><title>{`${i + 1} ${p.tag} ${md(p.start)}〜${md(p.end)} ${yen(p.value)}円`}</title></circle>
          <text className="nr-point-label" x={x(p.at)} y={y(p.value) - 9} textAnchor="middle">{i + 1}</text>
        </g>)}
        {layers.pivots && chart.pivots.map(p => <circle key={`${p.date}-${p.kind}`} className={`nr-pivot ${p.kind === 'TOP' ? 'is-top' : ''}`} cx={x(dayNumber(p.date))} cy={y(p.price)} r={3}>
          <title>{`${md(p.date)} ${p.kind === 'TOP' ? '山' : '谷'}・${md(p.confirmedOn)}に確定`}</title></circle>)}
        {layers.pivots && chart.pending && <circle className="nr-pending" cx={x(dayNumber(chart.pending.date))} cy={y(chart.pending.price)} r={5} />}
      </g>
      {layers.per && chart.current && multiples.map(m => <g key={m} className={`nr-per-label${strong.includes(m) ? ' is-near' : ''}`}>
        <line x1={x(dayNumber(chart.current!.morningOf))} x2={right + 5} y1={y(chart.current!.eps * m)} y2={y(chart.current!.eps * m)} />
        <text x={right + 8} y={y(chart.current!.eps * m) + 3}>PER{m} {yen(chart.current!.eps * m)}円</text></g>)}
      {[chart.start, chart.today, chart.end].map(d => <text className="nr-axis" key={d} x={x(dayNumber(d))} y={347}
        textAnchor={d === chart.start ? 'start' : d === chart.end ? 'end' : 'middle'}>{md(d)}</text>)}
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
      {external.map((p, i) => <button key={p.id} type="button" aria-pressed={selected === p.id} onClick={() => setSelected(selected === p.id ? null : p.id)}>
        {i + 1} {p.tag} · {md(p.start)}{p.end !== p.start ? `〜${md(p.end)}` : ''} · {yen(p.value)}円</button>)}
      {selectedPoint && <p>期間の中ほどに表示：{md(selectedPoint.start)}〜{md(selectedPoint.end)}、水準 {yen(selectedPoint.low)}〜{yen(selectedPoint.high)}円</p>}
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
