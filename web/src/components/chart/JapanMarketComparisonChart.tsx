import React, { useEffect, useId, useRef, useState } from 'react';
import type { ComparisonPoint, ForecastTrackRecordHorizon, JapanMarketComparison } from '../../types/japanMarketComparison';
import { useForecastTrackRecord } from '../../hooks/useJapanMarketComparison';
import { MaterialReactionLine, YardstickLine, noAnalogText } from './MaterialReactionLine';
import './JapanMarketComparisonChart.css';

const COLOURS = ['#94c5de', '#c7b6ed', '#dfbc83'];
// 2026-10-27 (owner): the closest windows when none is similar, one colour each
// and the year-month where the line starts, so which line is which year is clear.
const NEAR_COLOURS = ['#f0a35e', '#6fb6f2', '#c58df0'];
const yearMonth = (day: string) => `${day.slice(0, 4)}/${Number(day.slice(5, 7))}`;
const number = (value: number) => value.toLocaleString('ja-JP', { maximumFractionDigits: 1 });
const valuationNumber = (value: number) => value.toLocaleString('ja-JP', { maximumFractionDigits: 2 });
const percent = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(0)}%`;

/** Scorecard of the paths ARGUS actually issued, judged against "always the majority direction". */
function IssuedForecastRecord({ record, minimum }: { record: ForecastTrackRecordHorizon; minimum: number }) {
  const head = `実際に出した${record.horizonSessions}営業日後の見通しの成績：`;
  return <p className="jp-comparison__notice" data-forecast-track-record={record.status}>
    {record.status === 'INSUFFICIENT_SAMPLE'
      ? `${head}方向を示した${record.directionalForecasts}件を採点済み（${minimum}件で一致率）。`
      : `${head}方向を示した${record.directionalForecasts}件中${record.hits}件が一致（${percent(record.hitRate)}、95%信頼下限 ${percent(record.hitRateWilsonLower95)}）。`
        + `「いつも多数派の方向」と予想した場合は${percent(record.naiveMajorityRate)}で、`
        + (record.status === 'ABOVE_BASELINE' ? 'これを統計的に上回っています。'
          : 'これを統計的に上回っていません。')}
  </p>;
}

/** 2026-10-19: one or two admitted episodes are a thin basis. Say how many,
 *  how close they were to the limit, and that the computed line needs two. */
export function fewAnalogsText(document: JapanMarketComparison): string | null {
  const n = document.candidates.length;
  if (n === 0 || n > 2) return null;
  const items = document.candidates.map(candidate => {
    const closest = document.selectionAudit?.[candidate.anchorDate.slice(0, 4)]?.closest;
    const distance = closest && closest.anchorDate === candidate.anchorDate && typeof closest.distance === 'number' ? closest.distance : null;
    return `${candidate.anchorDate}${distance === null ? '' : `・距離${distance.toFixed(2)}`}`;
  });
  const limit = document.selectionPolicy ? `／上限${document.selectionPolicy.maximumDistance}` : '';
  return `似た局面は${n}件（${items.join('、')}${limit}）。`;
}

export function JapanMarketComparisonChart({ document }: { document: JapanMarketComparison }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(340);
  const [selectedId, setSelectedId] = useState('all');
  // Until the forecast rule passes its out-of-sample check it is a reference
  // path (median of past outcomes), not an outlook, and is named as such.
  // Owner instruction 2026-10-02: always draw it; the on/off switch is gone.
  const validated = document.forecast.validationStatus === 'VALIDATED';
  const forecastName = validated ? '計算予測' : '過去事例の中央値';
  const [showReferences, setShowReferences] = useState(true);
  const trackRecord = useForecastTrackRecord();
  const issued = trackRecord?.horizons[String(document.forecast.horizonSessions)];
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
  // Owner decision 2026-10-20: an unvalidated median path is not drawn. The
  // past analogues and what followed them stay as references; the line and
  // its band appear only once the rule passes its out-of-sample check.
  const forecast = validated ? document.forecast.line : [];
  const band = validated ? document.forecast.band : [];
  const nearest = document.candidates.length ? [] : document.nearestReferences ?? [];
  const references = [...candidates, ...nearest].flatMap(candidate => [...candidate.comparison,
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
  // The year-month where each reference starts (left), nudged apart so they never
  // overlap and never cover what followed each window on the right.
  const nearestLabels = nearest.map((reference, index) => {
    const start = reference.comparison.find(point => Number.isFinite(point.value));
    return { id: reference.snapshotId, anchorDate: reference.anchorDate, colour: NEAR_COLOURS[index % NEAR_COLOURS.length],
      x: left + 3, y: start ? y(start.value) - 5 : top + 12 * index };
  }).sort((a, b) => a.y - b.y);
  for (let index = 1; index < nearestLabels.length; index++)
    nearestLabels[index].y = Math.max(nearestLabels[index].y, nearestLabels[index - 1].y + 12);
  const showResearchNote = document.forecast.validationStatus !== 'VALIDATED';
  // Which evidence the selection used. When the market-condition history is
  // absent (after a deploy, until the next collection recalculates it) the
  // engine compares price shape alone, and the candidates and the computed
  // forecast differ from the market-condition comparison. Say so above the
  // chart, so a changed set of dates is read as a changed basis, not as noise.
  const priceShapeOnly = document.candidates.length > 0
    && document.candidates.every(candidate => candidate.missingGroups.includes('marketState'));
  // The series every selected candidate was compared on, and the defined
  // total, so "market conditions" is never left unqualified (2026-09-30:
  // six of sixteen, and the owner could not tell from the chart).
  const comparedAll = document.candidates.map(candidate => candidate.comparedFeatures ?? []);
  const comparedCommon = comparedAll.length
    ? comparedAll[0].filter(label => comparedAll.every(labels => labels.includes(label))) : [];
  const definedCount = document.candidates.find(candidate => candidate.stateFeatureDefinitionCount !== undefined)?.stateFeatureDefinitionCount;
  const marketStateNote = definedCount !== undefined
    ? `市場条件は${definedCount}系列中${comparedCommon.length}系列で比較${comparedCommon.length ? `（${comparedCommon.join('・')}）` : ''}`
    : '市場条件（信用残・VIX・為替・金利・NT倍率など、当時に入手できた値）';

  const few = fewAnalogsText(document);
  return <section className="jp-comparison" aria-labelledby={`${uniqueId}-title`}>
    <div className="jp-comparison__heading">
      <div><h2 id={`${uniqueId}-title`}>{validated ? '日経平均の見通し' : '日経平均と過去の類似局面'}</h2>
        <p>実績 {document.anchorDate}まで · {number(document.actualAnchorPrice)}円</p></div>
      <span>{document.forecast.horizonSessions}営業日先</span>
    </div>
    <p className="jp-comparison__scale">{document.unit === 'ANCHOR_100' ? '形状比較 · 基準日＝100' : '指数価格 · 円換算'}</p>
    {document.candidates.length > 0 && <p className="jp-comparison__basis" data-comparison-basis={priceShapeOnly ? 'price-shape-only' : 'price-and-market-state'}>
      比較の根拠：{priceShapeOnly
        ? '価格形状のみ（市場条件は再計算中）'
        : `価格形状＋${marketStateNote}`}
    </p>}
    {few && <p className="jp-comparison__notice" data-comparison-few={document.candidates.length}>{few}</p>}
    <div ref={container} className="jp-comparison__canvas">
      <svg viewBox={`0 0 ${width} ${height}`} role="img"
        aria-labelledby={`${uniqueId}-chart-title ${uniqueId}-chart-desc`}>
        <title id={`${uniqueId}-chart-title`}>日経平均の実績・過去の比較・その後の参考経路{validated ? '・計算予測' : ''}</title>
        <desc id={`${uniqueId}-chart-desc`}>白い実線が現在の実績。細い色線が過去局面の比較、同色の点線がその後の参考経路。
          {validated ? '緑の太い破線が現在条件による計算予測です。' : '点線は各過去事例のその後の動きで、方向の見通しではありません。'}過去の経路は将来の確定的な値動きではありません。</desc>
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
          {nearest.map((reference, index) => <g key={reference.snapshotId}>
            <path data-series="nearest-reference" data-anchor={reference.anchorDate}
              d={path(reference.comparison)} fill="none" stroke={NEAR_COLOURS[index % NEAR_COLOURS.length]}
              strokeWidth="1.6" strokeOpacity=".9" />
            {showReferences && <path data-series="nearest-subsequent-reference" data-anchor={reference.anchorDate}
              d={path(reference.subsequentReference)} fill="none" stroke={NEAR_COLOURS[index % NEAR_COLOURS.length]}
              strokeWidth="1.6" strokeDasharray="2 5" />}
          </g>)}
          <path data-series="current-actual" d={path(document.actual)} fill="none" stroke="#e1eaf0" strokeWidth="3" />
          {forecast.length > 0 && <path data-series="current-forecast" d={path(forecast)} fill="none"
            stroke="#79d6b0" strokeWidth="3" strokeDasharray="9 5" />}
        </g>
        {nearestLabels.map(label => <text key={label.id} data-nearest-label={label.anchorDate} x={label.x} y={label.y}
          textAnchor="start" fontSize="11" fontWeight="700"
          style={{ fill: label.colour, stroke: '#0d161c', strokeWidth: 3, paintOrder: 'stroke' }}>{yearMonth(label.anchorDate)}</text>)}
        <text x={left} y={height - 9}>{Math.abs(xMinimum)}営業日前</text>
        <text x={x(0)} y={height - 9} textAnchor="middle">{width < 480 ? "基準" : "基準日"}</text>
        <text x={right} y={height - 9} textAnchor="end">{width < 480 ? `+${xMaximum}日` : `${xMaximum}営業日先`}</text>
      </svg>
    </div>
    <ul className="jp-comparison__legend" aria-label="チャートの凡例">
      <li><i className="jp-comparison__sample jp-comparison__sample--actual" />現在の実績</li>
      {nearest.length > 0
        ? nearest.map((reference, index) => <li key={reference.snapshotId} data-nearest-reference={reference.anchorDate}>
          <i className="jp-comparison__sample jp-comparison__sample--near" style={{ borderColor: NEAR_COLOURS[index % NEAR_COLOURS.length] }} />
          参考 {reference.anchorDate}・距離{reference.distance.toFixed(2)}</li>)
        : <>
          <li><i className="jp-comparison__sample jp-comparison__sample--past" />過去の比較</li>
          <li><i className="jp-comparison__sample jp-comparison__sample--reference" />過去のその後</li>
        </>}
      {validated && <li><i className="jp-comparison__sample jp-comparison__sample--forecast" />現在の計算予測</li>}
    </ul>
    {document.historyCoverage && <p className="jp-comparison__scale">
      候補を探した期間：{document.historyCoverage.candidateStart ?? '確認できていません'}
      {document.historyCoverage.candidateEnd && `〜${document.historyCoverage.candidateEnd}`}。
      {document.historyCoverage.candidateCount.toLocaleString('ja-JP')}局面から
      {document.historyCoverage.selectedCount}件を表示しています{nearest.length ? `（参考${nearest.length}つ）` : ''}。
    </p>}
    <div className="jp-comparison__controls">
      <label>比較する局面 <select value={document.candidates.some(item => item.snapshotId === selectedId) ? selectedId : 'all'}
        onChange={event => setSelectedId(event.target.value)}>
        <option value="all">すべての候補</option>
        {document.candidates.map(candidate => <option key={candidate.snapshotId} value={candidate.snapshotId}>{candidate.anchorDate}</option>)}
      </select></label>
      <label><input type="checkbox" checked={showReferences} onChange={event => setShowReferences(event.target.checked)} />その後の参考経路</label>
    </div>
    {document.retainedNoteJa && <p className="jp-comparison__notice" data-comparison-retained="true">{document.retainedNoteJa}</p>}
    {!document.candidates.length && <p className="jp-comparison__notice" data-nearest-count={nearest.length}>
      {nearest.length ? `似た局面なし（上限${document.selectionPolicy?.maximumDistance ?? 1}）・最も近い${nearest.length}つを参考に表示` : '似た局面なし'}</p>}
    {document.candidates.length > 0 && document.candidates.every(candidate => candidate.comparisonKind === 'PARTIAL_COMPARISON') &&
      <p className="jp-comparison__notice">一部の条件だけで比較</p>}
    {!document.forecast.line.length && validated && <p className="jp-comparison__notice">{noAnalogText(document) ?? (document.candidates.length === 1
      ? `${forecastName}なし（1件）`
      : `${forecastName}なし（事例不足）`)}</p>}
    {!validated && !document.candidates.length && noAnalogText(document) && <p className="jp-comparison__notice">{noAnalogText(document)}</p>}
    {showResearchNote && <p className="jp-comparison__notice" data-forecast-role="references-only">
      {document.forecast.validation
        ? `予想の線なし：方向一致率 ${document.forecast.validation.hitRate === null ? '—' : (document.forecast.validation.hitRate * 100).toFixed(0) + '%'}（いつも多数派の予想 ${document.forecast.validation.naiveMajorityRate === null ? '—' : (document.forecast.validation.naiveMajorityRate * 100).toFixed(0) + '%'}・過去10年）`
        : '予想の線なし'}</p>}
    {issued && trackRecord && <IssuedForecastRecord record={issued} minimum={trackRecord.minimumDirectionalForecasts} />}
    <details className="jp-comparison__details"><summary>比較元と検証</summary>
      <p>{document.scaleExplanation}</p>
      {document.reviewConditionsJa && <section aria-label="比較を見直す条件">
        <h3>比較を見直すとき</h3>
        {document.reviewConditionsJa.map(line => <p key={line}>{line}</p>)}
      </section>}
      {document.historyCoverage && <>
        <p>価格の収録：{document.historyCoverage.sourceStart}〜{document.historyCoverage.sourceEnd}
          （{document.historyCoverage.sourceBars.toLocaleString('ja-JP')}営業日）</p>
        <p>年別の検索対象：{Object.entries(document.historyCoverage.candidatesByYear)
          .map(([year, count]) => `${year}年 ${count}局面`).join(' / ')}</p>
        <p>営業日表または価格の欠損による除外：
          {document.historyCoverage.excluded.missingCalendarOrPriceSession}局面</p>
      </>}
      {document.selectionPolicy && (() => {
        const scales = Object.values(document.selectionPolicy.stateScales);
        const robust = scales.filter(scale => scale.basis === 'ROBUST_MAD_HISTORY').length;
        return <p>物差し：市場条件{scales.length}系列（頑健な散布度{robust}・定義値{scales.length - robust}）・採用上限{document.selectionPolicy.maximumDistance}・最大{document.selectionPolicy.maximumCandidates}件</p>;
      })()}
      {document.selectionAudit?.['2018'] && (() => {
        const audit = document.selectionAudit['2018'];
        const closest = audit.closest;
        const result = !closest ? '比較可能な候補を確認できませんでした。'
          : closest.status === 'SELECTED' ? `${closest.anchorDate}が選ばれました。`
          : closest.status === 'DISTANCE_ABOVE_THRESHOLD'
            ? `${closest.anchorDate}が最も近い候補でしたが、距離 ${closest.distance.toFixed(3)} が採用上限を超えました。`
            : `${closest.anchorDate}は順位 ${closest.rank ?? '未確認'} でしたが、より近い候補または重複区間の除外により表示対象外です。`;
        return <section aria-label="2018年の比較検索記録">
          <h3>2018年を検索した結果</h3>
          <p>同じ情報締切・同じ条件で{audit.candidateCount}局面を検索し、
            {audit.admittedCount}局面が距離条件を満たし、{audit.selectedCount}局面を表示対象にしました。{result}</p>
        </section>;
      })()}

      {document.valuationEvidence && document.valuationEvidence.epsKind === 'MARKET_CAP_WEIGHTED_FORWARD_ESTIMATE' &&
        <p data-valuation-basis="argus-current-estimate">
          {document.valuationEvidence.date}のPER {valuationNumber(document.valuationEvidence.per)}倍、
          指数EPS {valuationNumber(document.valuationEvidence.eps)}円（推計）。
        </p>}
      {document.valuationEvidence && document.valuationEvidence.epsKind !== 'MARKET_CAP_WEIGHTED_FORWARD_ESTIMATE'
        && (document.valuationEvidence.epsKind === 'PROXY_FROM_CONSTITUENT_FORECAST_EPS'
        ? <p data-valuation-basis="argus-proxy">
          {document.valuationEvidence.date}の指数ベースPER {valuationNumber(document.valuationEvidence.per)}倍、
          指数EPS {valuationNumber(document.valuationEvidence.eps)}円（代理値）。
        </p>
        : <p data-valuation-basis="official">
          {document.valuationEvidence.date}の指数ベースPER {valuationNumber(document.valuationEvidence.per)}倍、
          概算EPS {valuationNumber(document.valuationEvidence.eps)}円。
          <a href={document.valuationEvidence.sourceRef} target="_blank" rel="noreferrer">日経公式の算出資料</a>
        </p>)}
      {document.sourceAcquisition && <section aria-label="公式データの収録範囲">
        <h3>公式データの収録範囲</h3>
        {Object.entries(document.sourceAcquisition.sources).map(([key, source]) => <p key={key}>
          {key === 'jp_yield_curve' ? '日本国債金利（財務省）' : 'VIX（Cboe）'}：
          {source.firstDate ?? '未取得'}{source.lastDate && `〜${source.lastDate}`}、
          {source.observations.toLocaleString('ja-JP')}観測日。
        </p>)}
        {!Object.keys(document.sourceAcquisition.sources).length && <p>取込待ち</p>}
      </section>}
      <p>情報締切：{new Date(document.informationCutoff).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} JST</p>
      {candidates.map(candidate => <article key={candidate.snapshotId}>
        <h3>{candidate.anchorDate}を基準とする{candidate.comparisonKind === 'MARKET_ANALOG' ? '市場比較' : '部分比較'}</h3>
        <p>{candidate.similarReasons.join('。')}</p>
        <p>相違・不足：{candidate.differences.join('。')}</p>
      </article>)}
      {document.forecast.sampleCount > 0 && <p>
        比較事例{document.forecast.sampleCount}件の{document.forecast.horizonSessions}営業日後：
        上昇{document.forecast.counts.up}件、横ばい{document.forecast.counts.flat}件、下落{document.forecast.counts.down}件。
        横ばい＝±{document.forecast.flatThresholdPct}%以内。
      </p>}
      {document.forecast.validation && (() => {
        const v = document.forecast.validation;
        const pct = (n: number | null) => n === null ? '—' : `${(n * 100).toFixed(1)}%`;
        const reasonJa: Record<string, string> = {
          too_few_independent_evaluations: '検証100件未満',
          direction_not_better_than_naive_majority: '単純な予想を上回らない',
          band_coverage_outside_35_65_percent: '帯の的中が35〜65%の外',
        };
        return <section aria-label="計算予測の過去検証" data-forecast-validation={v.validationStatus}>
          <h3>この計算予測の過去検証（{document.forecast.horizonSessions}営業日後）</h3>
          <p>{v.evaluationStart}〜{v.evaluationEnd}：重ならない{v.evaluations}件のうち方向を示した{v.directionalEvaluations}件で、方向の一致率は{pct(v.hitRate)}
            （95%信頼下限 {pct(v.hitRateWilsonLower95)}）、「いつも多数派の方向」と予想した場合は{pct(v.naiveMajorityRate)}でした。
            帯（事例の中央半分）の中に実際の値が入った割合は{pct(v.bandCoverage)}（目安50%）です。</p>
          <p>{v.validationStatus === 'VALIDATED'
            ? '判定：過去検証の基準を満たしています。'
            : `判定：${v.reasons.map(reason => reasonJa[reason] ?? reason).join('。')}。`}</p>
        </section>;
      })()}
      {document.forecast.weightSearch && (() => {
        const w = document.forecast.weightSearch;
        const pct = (n: number | null) => n === null ? '—' : `${(n * 100).toFixed(1)}%`;
        const weights = Object.entries(w.chosenWeights).map(([key, value]) =>
          `${({ priceShape: '価格形状', marketState: '市場条件', conditionOrder: '七サインの順序', materialReaction: '材料反応' } as Record<string, string>)[key] ?? key}×${value}`).join('・');
        return <section aria-label="重み付けの再検証" data-weight-search={w.adopted ? 'adopted' : 'not-adopted'}>
          <h3>比較の重み付けの再検証</h3>
          <p>{w.gridSize}通りの重み付けを{w.trainStart}〜{w.trainEnd}で比べ、最も良かった「{weights}」を
            {w.confirmStart ? `${w.confirmStart}〜${w.confirmEnd}で採用するか判断し、どちらにも使っていない` : '選ぶときに使っていない'}{w.testStart}〜{w.testEnd}で成績を測りました。
            {w.choiceHorizon}営業日後の方向一致率は{pct(w.testHitRate)}（95%信頼下限 {pct(w.testWilsonLower95)}）、
            単純予想は{pct(w.testNaiveRate)}、等しい重みでは{pct(w.equalWeightsTestHitRate)}でした。</p>
          <p>{w.adopted ? '判定：基準を満たしたため採用'
            : '判定：基準未達のため不採用'}</p>
        </section>;
      })()}
      <MaterialReactionLine research={document.forecast.materialReactionResearch} />
      <YardstickLine research={(document.forecast as Record<string, unknown>).yardstickResearch} />
      {document.forecast.signEventStudy && <p><a href="#today-seven-conditions">七条件の向き・過去成績を見る</a></p>}

    </details>
  </section>;
}
