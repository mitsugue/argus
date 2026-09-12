import React, { useEffect, useId, useRef, useState } from 'react';
import type { ComparisonPoint, JapanMarketComparison } from '../../types/japanMarketComparison';
import './JapanMarketComparisonChart.css';

const COLOURS = ['#94c5de', '#c7b6ed', '#dfbc83'];
const number = (value: number) => value.toLocaleString('ja-JP', { maximumFractionDigits: 1 });

export function JapanMarketComparisonChart({ document }: { document: JapanMarketComparison }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(340);
  const [selectedId, setSelectedId] = useState('all');
  const [showForecast, setShowForecast] = useState(true);
  const [showReferences, setShowReferences] = useState(true);
  const uniqueId = useId().replace(/:/g, '');
  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(260, entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const candidates = document.candidates.filter(candidate => selectedId === 'all'
    || candidate.snapshotId === selectedId || !document.candidates.some(item => item.snapshotId === selectedId));
  const forecast = showForecast ? document.forecast.line : [];
  const band = showForecast ? document.forecast.band : [];
  const references = candidates.flatMap(candidate => [...candidate.comparison,
    ...(showReferences ? candidate.subsequentReference : [])]);
  const points = [...document.actual, ...references, ...forecast];
  const finitePoints = points.filter(point => Number.isFinite(point.value) && Number.isFinite(point.offsetSessions));
  const values = [...finitePoints.map(point => point.value), ...band.flatMap(point => [point.lower, point.upper])]
    .filter(Number.isFinite);
  const xMinimum = Math.min(-1, ...finitePoints.map(point => point.offsetSessions));
  const xMaximum = Math.max(document.forecast.horizonSessions, ...finitePoints.map(point => point.offsetSessions));
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 1;
  const pad = Math.max((maximum - minimum) * .12, document.unit === 'ANCHOR_100' ? .2 : 1);
  const yMinimum = minimum - pad;
  const yMaximum = maximum + pad;
  const height = 310;
  const left = document.unit === 'ANCHOR_100' ? 43 : 66;
  const right = width - 12;
  const top = 28;
  const bottom = height - 35;
  const x = (value: number) => left + (value - xMinimum) / (xMaximum - xMinimum) * (right - left);
  const y = (value: number) => bottom - (value - yMinimum) / (yMaximum - yMinimum) * (bottom - top);
  const path = (rows: ComparisonPoint[]) => rows.filter(point => Number.isFinite(point.value))
    .map((point, index) => `${index ? 'L' : 'M'}${x(point.offsetSessions).toFixed(2)},${y(point.value).toFixed(2)}`).join(' ');
  const bandPath = band.length ? path(band.map(point => ({ offsetSessions: point.offsetSessions, value: point.upper })))
    + ' ' + [...band].reverse().map(point => `L${x(point.offsetSessions)},${y(point.lower)}`).join(' ') + ' Z' : '';
  const ticks = Array.from({ length: 5 }, (_, index) => yMinimum + (yMaximum - yMinimum) * index / 4);
  const showResearchNote = document.forecast.validationStatus !== 'VALIDATED';

  return <section className="jp-comparison" aria-labelledby={`${uniqueId}-title`}>
    <div className="jp-comparison__heading">
      <div><h2 id={`${uniqueId}-title`}>日経平均の見通し</h2>
        <p>実績 {document.anchorDate}まで · {number(document.actualAnchorPrice)}円</p></div>
      <span>{document.forecast.horizonSessions}営業日先</span>
    </div>
    <p className="jp-comparison__scale">{document.unit === 'ANCHOR_100' ? '形状比較 · 基準日＝100' : '指数価格 · 円換算'}</p>
    <div ref={container} className="jp-comparison__canvas">
      <svg viewBox={`0 0 ${width} ${height}`} role="img"
        aria-labelledby={`${uniqueId}-chart-title ${uniqueId}-chart-desc`}>
        <title id={`${uniqueId}-chart-title`}>日経平均の実績・過去の比較・その後の参考経路・計算予測</title>
        <desc id={`${uniqueId}-chart-desc`}>白い実線が現在の実績。細い色線が過去局面の比較、同色の点線がその後の参考経路。
          緑の太い破線が現在条件による計算予測です。過去の経路は将来の確定的な値動きではありません。</desc>
        <defs><clipPath id={`${uniqueId}-clip`}><rect x={left} y={top} width={right - left} height={bottom - top} /></clipPath></defs>
        {ticks.map((value, index) => <g key={index}>
          <line x1={left} x2={right} y1={y(value)} y2={y(value)} className="jp-comparison__grid" />
          <text x={left - 7} y={y(value) + 4} textAnchor="end">{number(value)}</text>
        </g>)}
        <line x1={x(0)} x2={x(0)} y1={top} y2={bottom} className="jp-comparison__anchor" />
        <g clipPath={`url(#${uniqueId}-clip)`}>
          {bandPath && <path data-series="forecast-band" d={bandPath} fill="#79d6b0" fillOpacity=".13" />}
          {candidates.map(candidate => {
            const colour = COLOURS[document.candidates.indexOf(candidate) % COLOURS.length];
            return <g key={candidate.snapshotId}>
              <path data-series="past-comparison" data-anchor={candidate.anchorDate}
                d={path(candidate.comparison)} fill="none" stroke={colour} strokeWidth="1.7" strokeOpacity=".9" />
              {showReferences && <path data-series="past-subsequent-reference" data-anchor={candidate.anchorDate}
                d={path(candidate.subsequentReference)} fill="none" stroke={colour} strokeWidth="1.8" strokeDasharray="2 5" />}
            </g>;
          })}
          <path data-series="current-actual" d={path(document.actual)} fill="none" stroke="#e1eaf0" strokeWidth="3" />
          {forecast.length > 0 && <path data-series="current-forecast" d={path(forecast)} fill="none"
            stroke="#79d6b0" strokeWidth="3" strokeDasharray="9 5" />}
        </g>
        <text x={left} y={height - 9}>{Math.abs(xMinimum)}営業日前</text>
        <text x={x(0)} y={height - 9} textAnchor="middle">{width < 480 ? "基準" : "基準日"}</text>
        <text x={right} y={height - 9} textAnchor="end">{width < 480 ? `+${xMaximum}日` : `${xMaximum}営業日先`}</text>
      </svg>
    </div>
    <ul className="jp-comparison__legend" aria-label="チャートの凡例">
      <li><i className="jp-comparison__sample jp-comparison__sample--actual" />現在の実績</li>
      <li><i className="jp-comparison__sample jp-comparison__sample--past" />過去の比較</li>
      <li><i className="jp-comparison__sample jp-comparison__sample--reference" />過去のその後</li>
      <li><i className="jp-comparison__sample jp-comparison__sample--forecast" />現在の計算予測</li>
    </ul>
    <div className="jp-comparison__controls">
      <label>比較する局面 <select value={document.candidates.some(item => item.snapshotId === selectedId) ? selectedId : 'all'}
        onChange={event => setSelectedId(event.target.value)}>
        <option value="all">すべての候補</option>
        {document.candidates.map(candidate => <option key={candidate.snapshotId} value={candidate.snapshotId}>{candidate.anchorDate}</option>)}
      </select></label>
      <label><input type="checkbox" checked={showReferences} onChange={event => setShowReferences(event.target.checked)} />その後の参考経路</label>
      <label><input type="checkbox" checked={showForecast} onChange={event => setShowForecast(event.target.checked)} />計算予測と帯</label>
    </div>
    {!document.candidates.length && <p className="jp-comparison__notice">十分に似た過去局面は見つかっていません。</p>}
    {document.candidates.length > 0 && document.candidates.every(candidate => candidate.comparisonKind === 'PARTIAL_COMPARISON') &&
      <p className="jp-comparison__notice">比較できるのは一部の条件です。市場状態全体が似ていると判断できる根拠は、まだ不足しています。</p>}
    {!document.forecast.line.length && <p className="jp-comparison__notice">計算予測を出すための比較事例が不足しています。</p>}
    {showResearchNote && document.forecast.line.length > 0 && <p className="jp-comparison__notice">
      計算予測は検証中です。帯は比較事例の中央半分の範囲で、将来の価格が入る確率ではありません。</p>}
    <details className="jp-comparison__details"><summary>比較元・尺度・検証状態を見る</summary>
      <p>{document.scaleExplanation}</p>
      <p>情報締切：{new Date(document.informationCutoff).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} JST</p>
      {candidates.map(candidate => <article key={candidate.snapshotId}>
        <h3>{candidate.anchorDate}を基準とする{candidate.comparisonKind === 'MARKET_ANALOG' ? '市場比較' : '部分比較'}</h3>
        <p>{candidate.similarReasons.join('。')}</p>
        <p>相違・不足：{candidate.differences.join('。')}</p>
      </article>)}
      {document.forecast.sampleCount > 0 && <p>
        比較事例{document.forecast.sampleCount}件の{document.forecast.horizonSessions}営業日後：
        上昇{document.forecast.counts.up}件、横ばい{document.forecast.counts.flat}件、下落{document.forecast.counts.down}件。
        横ばいは±{document.forecast.flatThresholdPct}%以内です。事例の頻度であり、予測的中率ではありません。
      </p>}
      <ul>{document.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul>
    </details>
  </section>;
}
