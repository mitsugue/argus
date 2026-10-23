import React from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { currentLevelMap, evidenceJa, nearestPerRows, rowLabelJa, validValuationHistory, type LevelMapRow, type LevelMapScore, type LevelMapState } from '../../lib/levelMap';
import './LevelMapCard.css';
import { WeightedPerInput } from './WeightedPerInput';
import { withoutScreenNotes } from '../../lib/screenNotes';

// Nikkei morning level map (2026-10-04). The map is fixed before the open and
// scored afterwards by fixed rules. Past frequencies, not probabilities; the
// same accuracy as "previous close ± 2 ATR"; never a trading signal.
const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
const signed = (v: number, digits = 1) => `${v > 0 ? '+' : ''}${v.toFixed(digits)}`;
const jst = (iso?: string | null) => iso && Number.isFinite(Date.parse(iso))
  ? new Date(iso).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';

function Row({ row }: { row: LevelMapRow }) {
  return <tr data-side={row.side} data-kinds={row.kinds.join(',')}>
    <td className="lm-price">{yen(row.price)}</td>
    <td>{signed(row.distancePct)}%<small>（{signed(row.distanceAtr)}ATR）</small></td>
    <td>{rowLabelJa(row)}<small>{evidenceJa(row)}</small></td>
    <td>{row.bandJa ?? '−'}</td>
    <td>{row.reachedWithin10SessionsPct != null ? `${row.reachedWithin10SessionsPct}%` : '−'}</td>
    <td>{row.sessionsMedian != null ? `${row.sessionsMedian}日（${row.sessions25}〜${row.sessions75}）` : '−'}</td>
  </tr>;
}

function Tally({ score, title }: { score: LevelMapScore; title: string }) {
  const t = score.turningPoints, p = score.phaseOutcomes, f = score.fakeLineOutcomes;
  return <div className="lm-tally" data-pre-registered={score.preRegisteredOnly ? '1' : '0'}>
    <b>{title}</b>
    <p>朝 {score.mornings}回 · 線に届いた局面 {score.phases}（止まった {p.STOPPED} · 突き抜けた {p.BROKE} · 未決 {p.UNDECIDED + p.OPEN}）</p>
    <p>比べる基準（倍率を±0.25・±0.5ずらした偽の線）: 止まった {f.STOPPED} · 突き抜けた {f.BROKE}</p>
    <p>確定した転換点 {t.evaluated}個のうち整数PER線の±1%以内 {t.perLineHits}個（偶然の目安 {t.chanceExpected.toFixed(1)}個）· 今の値±2ATRの±1%以内 {t.atr2Hits}個</p>
  </div>;
}

function Calculations({ map, current, suppliedDays, notes = true }: { map: NonNullable<LevelMapState['latest']>; current: boolean; suppliedDays: number; notes?: boolean }) {
  const cov = map.epsCoverage;
  const supplied = cov?.suppliedEarnings ?? 0;
  return <>
    <p className="lm-note">{current ? `${map.previousSession} 終値の表示用計算` : `${map.morningOf} 朝 · 寄付前に固定保存`}（{jst(map.createdAt)}）</p>
    <p className="lm-note">{current ? '最新終値' : '前日終値'} {yen(map.previousClose)}（{map.previousSession}）· ATR14 {yen(map.atr14)} ·
      EPS {map.eps.toFixed(1)}（{map.epsDate}）· PER {map.per.toFixed(2)}倍</p>
    <p className="lm-note lm-eps">{map.epsLabelJa}{cov ? `。予想が無く実績で補った社 ${cov.filledFromTrailing ?? 0}・赤字予想 ${cov.negativeForecast ?? 0}` : ''}
      {map.constituentsAsOf ? `。構成銘柄は ${map.constituentsAsOf} 時点` : ''}</p>
    {supplied > 0 && <p className="lm-note lm-supplied" data-supplied={supplied}>この日は補った推計（{supplied}社）</p>}
    {suppliedDays > 0 && <p className="lm-small lm-supplied-days" data-supplied-days={suppliedDays}>過去の推計のうち{suppliedDays}日は補った推計</p>}
    {map.epsJumped && <p className="lm-note lm-jump">EPSが前の推計から3%以上変化</p>}
    <div className="lm-scroll"><table className="lm-table">
      <thead><tr><th>価格（円）</th><th>{current ? '最新終値との差' : '前日終値との差'}</th><th>この価格の意味</th><th>山・谷ができた頻度</th><th>10営業日以内に届いた</th><th>到達までの日数</th></tr></thead>
      <tbody>
        {map.rows.filter(r => r.side === 'UP').sort((a,b) => b.price-a.price).map((row, i) => <Row key={`u${i}`} row={row} />)}
        <tr className="lm-now"><td>{yen(map.previousClose)}</td><td colSpan={5}>{current ? '最新終値' : '前日終値'}</td></tr>
        {map.rows.filter(r => r.side === 'DOWN').sort((a,b) => b.price-a.price).map((row, i) => <Row key={`d${i}`} row={row} />)}
      </tbody>
    </table></div>
    <p className="lm-guides">距離の目安 上 +1/+2/+3ATR: {map.atrGuides.UP.map(yen).join(' / ')}　下 −1/−2/−3ATR: {map.atrGuides.DOWN.map(yen).join(' / ')}</p>
    {notes && <ul className="lm-fixed">{map.fixedNotesJa.map(note => withoutScreenNotes(note)).filter(Boolean).map((note, i) => <li key={i}>{note}</li>)}</ul>}
  </>;
}

export function LevelMapView({ state }: { state: LevelMapState | null | undefined }) {
  const map = state ? currentLevelMap(state) : null;
  const current = !!state?.chart?.displayMap && map === state.chart.displayMap;
  if (!state || !map || !state.latest) return null;
  const history = validValuationHistory(state.chart?.valuationHistory)
    && state.chart.valuationHistory.lastDate <= map.epsDate ? state.chart.valuationHistory : null;
  const perRows = nearestPerRows(map, state.chart?.nearest);
  const above = perRows.filter(r => r.side === 'UP').sort((a, b) => a.price - b.price)[0];
  const below = perRows.filter(r => r.side === 'DOWN').sort((a, b) => b.price - a.price)[0];
  return <section id="today-price-scale" className="lm-card card" aria-label="日経平均の価格の目盛り" data-argus-contract="level-map-v1"
    data-morning={map.morningOf}>
    <header className="lm-heading"><b>PRICE LEVELS</b><span>PER · {current ? `${map.previousSession.slice(5).replace('-', '/')}終値` : `${map.morningOf.slice(5).replace('-', '/')}朝の保存値`}</span></header>
    {state.chart?.closePending === true && /^\d{4}-\d{2}-\d{2}$/.test(state.chart.today ?? '') && state.chart.today! > map.previousSession && <p role="status" className="lm-note">{state.chart.today!.slice(5).replace('-', '/')}の終値は取得待ち。{map.previousSession.slice(5).replace('-', '/')}の終値を表示しています。</p>}
    <div className="lm-price-ladder" aria-label="価格と利益の倍率">
      {above && <article data-side="UP"><span>{above.multiple}倍まで上がると</span><b>{yen(above.price)}<small>円</small></b><strong>{signed(above.distancePct)}%</strong></article>}
      <article data-side="NOW"><span>{current ? '最新終値' : '前日終値'} · {map.per.toFixed(2)}倍</span><b>{yen(map.previousClose)}<small>円</small></b><small>{map.previousSession.slice(5).replace('-', '/')}の終値</small></article>
      {below && <article data-side="DOWN"><span>{below.multiple}倍まで下がると</span><b>{yen(below.price)}<small>円</small></b><strong>{signed(below.distancePct)}%</strong></article>}
    </div>
    {current && <p className="lm-note">EPS {map.epsDate.slice(5).replace('-', '/')}推計{state.chart?.displayMap?.valuationPending ? '・当日分の入力待ち' : ''}</p>}
    <div className="lm-use">
      <b>過去と比べて、利益に対する株価は高いか</b>
      {history?.sufficient && above?.multiple === history.upperMultiple ? <>
        <p><strong>{history.upperMultiple}倍は、この期間の中央値{history.median.toFixed(1)}倍{history.upperMultiple > history.median ? 'より上' : history.upperMultiple < history.median ? 'より下' : 'と同じ位置'}です。</strong></p>
        <p>{history.upperMultiple}倍以上の日は <strong>{history.atOrAboveUpper} / {history.count}営業日</strong>。最高は{history.maximum.toFixed(1)}倍でした。</p>
        <small>{history.firstDate.replaceAll('-', '/')}〜{history.lastDate.replaceAll('-', '/')} · 同じ方式で再計算{history.missingSessions ? ` · 未集計${history.missingSessions}日` : ''}</small>
      </> : <p>集計中</p>}
    </div>
    <div className="lm-reach" aria-label="同じ距離の過去の到達割合">
      {[above, below].filter((r): r is LevelMapRow => !!r).map(row => <article key={row.side} data-side={row.side}>
        <b>{row.side === 'UP' ? '上の価格まで' : '下の価格まで'}</b>
        <strong>{Number.isFinite(row.reachedWithin10SessionsPct) ? `${row.reachedWithin10SessionsPct}%` : '未集計'}</strong>
        <span>10営業日以内に届いた割合（過去・同じ距離）</span>
      </article>)}
    </div>
    <details className="lm-all-levels"><summary>価格一覧・計算の根拠</summary>
    <Calculations map={map} current={current} suppliedDays={Number.isInteger(state.estimateSuppliedCount) ? state.estimateSuppliedCount! : 0} />
    </details>
    <details className="lm-records"><summary>PER線の答え合わせ・過去の記録</summary>
    {current && <details className="lm-morning"><summary>朝の固定記録を見る</summary><Calculations map={state.latest} current={false} suppliedDays={0} notes={false} /></details>}
    {state.missedMornings.length > 0 && <p className="lm-small">寄付前に作れなかった朝: {state.missedMornings.join('、')}</p>}
    {state.score && <Tally score={state.score} title={`答え合わせ（${state.score.firstMorning ?? ''}からの事前記録）`} />}
    {state.score && state.score.mornings < 60 && <p className="lm-small">件数不足（{state.score.mornings}/60朝）</p>}
    {state.retrospective && state.retrospective.mornings > 0 && <details className="lm-retro">
      <summary>後から数えた分（{state.retrospective.firstMorning}〜）</summary>
      <Tally score={state.retrospective} title="後から数えた分" />
    </details>}
    </details>
  </section>;
}

/** Today: the five-session comparison reply carries the stored morning map. */
export function LevelMapCard() {
  const state = useJapanMarketComparison(5);
  if (!state.levelMap?.latest) return <><section className="lm-card card" aria-label="日経平均の価格の目盛り">
    <header className="lm-heading"><b>PRICE LEVELS</b></header>
    <p role="status">{state.loading ? '読み込み中' : state.levelMapError ? '取得できません' : '準備中'}</p>
    {state.levelMapError && <button type="button" onClick={state.retry}>再取得</button>}
  </section><WeightedPerInput /></>;
  return <><LevelMapView state={state.levelMap} /><WeightedPerInput />{state.levelMapError && <p role="status">更新失敗・保存分</p>}</>;
}
