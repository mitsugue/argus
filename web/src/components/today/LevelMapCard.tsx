import React from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { currentLevelMap, evidenceJa, rowLabelJa, validValuationHistory, type LevelMapRow, type LevelMapScore, type LevelMapState } from '../../lib/levelMap';
import './LevelMapCard.css';

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

export function LevelMapView({ state }: { state: LevelMapState | null | undefined }) {
  const map = state ? currentLevelMap(state) : null;
  const current = !!state?.chart?.displayMap && map === state.chart.displayMap;
  if (!state || !map || !state.latest) return null;
  const cov = state.latest?.epsCoverage;
  const history = validValuationHistory(state.chart?.valuationHistory)
    && state.chart.valuationHistory.lastDate <= map.epsDate ? state.chart.valuationHistory : null;
  const perRows = map.rows.filter(r => r.kinds.includes('PER_LINE'));
  const above = perRows.filter(r => r.side === 'UP').sort((a, b) => a.price - b.price)[0];
  const below = perRows.filter(r => r.side === 'DOWN').sort((a, b) => b.price - a.price)[0];
  const examples = [above && `${yen(above.price)}円まで上がると${above.multiple}倍`,
    below && `${yen(below.price)}円まで下がると${below.multiple}倍`].filter(Boolean);
  const distances = [above && `上の目印までは${signed(above.distancePct)}%`,
    below && `下の目印までは${signed(below.distancePct)}%`].filter(Boolean);
  return <section id="today-price-scale" className="lm-card card" aria-label="日経平均の価格の目盛り" data-argus-contract="level-map-v1"
    data-morning={map.morningOf}>
    <header className="lm-heading"><b>日経平均の価格の目盛り</b><span>PER · {current ? `${map.previousSession.slice(5).replace('-', '/')}終値` : `${map.morningOf.slice(5).replace('-', '/')}朝の保存値`}</span></header>
    <div className="lm-reading">
      <p>この表は、<strong>企業の利益に対して、日経平均が何倍の値段になっているか</strong>を示す目盛りです。</p>
    </div>
    <div className="lm-price-ladder" aria-label="価格と利益の倍率">
      {above && <article data-side="UP"><span>{above.multiple}倍まで上がると</span><b>{yen(above.price)}<small>円</small></b><strong>{signed(above.distancePct)}%</strong></article>}
      <article data-side="NOW"><span>{current ? '最新終値' : '前日終値'} · {map.per.toFixed(2)}倍</span><b>{yen(map.previousClose)}<small>円</small></b><small>{map.previousSession.slice(5).replace('-', '/')}の終値</small></article>
      {below && <article data-side="DOWN"><span>{below.multiple}倍まで下がると</span><b>{yen(below.price)}<small>円</small></b><strong>{signed(below.distancePct)}%</strong></article>}
    </div>
    {current && <p className="lm-note">EPSは{map.epsDate.slice(5).replace('-', '/')}の推計です。{state.chart?.displayMap?.valuationPending ? '当日分の入力待ち。終値を先に更新しています。' : '当日分のPER・価格の目盛りを再計算済みです。'}朝の事前記録は答え合わせに残しています。</p>}
    <div className="lm-use">
      <b>過去と比べて、利益に対する株価は高いか</b>
      {history?.sufficient && above?.multiple === history.upperMultiple ? <>
        <p><strong>{history.upperMultiple}倍は、この期間の中央値{history.median.toFixed(1)}倍{history.upperMultiple > history.median ? 'より上' : history.upperMultiple < history.median ? 'より下' : 'と同じ位置'}です。</strong></p>
        <p>{history.upperMultiple}倍以上の日は <strong>{history.atOrAboveUpper} / {history.count}営業日</strong>。最高は{history.maximum.toFixed(1)}倍でした。</p>
        <small>{history.firstDate.replaceAll('-', '/')}〜{history.lastDate.replaceAll('-', '/')} · 同じ方式で再計算{history.missingSessions ? ` · 未集計${history.missingSessions}日` : ''}</small>
      </> : <p>同じ計算方式の過去データを集計中です。</p>}
      <p>利益に対して高いかを比べる目盛りです。{above?.multiple ?? '整数の'}倍が天井という意味ではありません。</p>
    </div>
    <div className="lm-reach" aria-label="同じ距離の過去の到達割合">
      {[above, below].filter((r): r is LevelMapRow => !!r).map(row => <article key={row.side} data-side={row.side}>
        <b>{row.side === 'UP' ? '上の価格まで' : '下の価格まで'}</b>
        <strong>{Number.isFinite(row.reachedWithin10SessionsPct) ? `${row.reachedWithin10SessionsPct}%` : '未集計'}</strong>
        <span>同じくらいの距離で、10営業日以内に届いた過去の割合</span>
      </article>)}
      <small>同じ距離帯の集計です。今後の確率や、反発した割合ではありません。</small>
    </div>
    <details className="lm-explanation"><summary>倍率と価格の読み方</summary>
      <p>たとえば、{current ? '最新終値は' : 'この朝は'}約{map.per.toFixed(2)}倍。{examples.length > 0 && `日経平均が${examples.join('、')}になります。`}</p>
      {distances.length > 0 && <p>{current ? '最新終値' : '前日終値'} {yen(map.previousClose)}円から、{distances.join('、')}です。</p>}
      <small>株価が動いた時の位置を確かめる表です。ここで反転するかは未確認のため、売買時期の判断には使えません。</small>
    </details>
    <details className="lm-all-levels"><summary>すべての価格・計算の根拠</summary>
    <p className="lm-note">{state.latest!.morningOf} 朝 · 寄付前に固定保存（{jst(state.latest!.createdAt)}）</p>
    <p className="lm-note">前日終値 {yen(state.latest!.previousClose)}（{state.latest!.previousSession}）· ATR14 {yen(state.latest!.atr14)} ·
      EPS {state.latest!.eps.toFixed(1)}（{state.latest!.epsDate}）· PER {state.latest!.per.toFixed(2)}倍</p>
    <p className="lm-note lm-eps">{state.latest!.epsLabelJa}{cov ? `。予想が無く実績で補った社 ${cov.filledFromTrailing ?? 0}・赤字予想 ${cov.negativeForecast ?? 0}` : ''}
      {state.latest!.constituentsAsOf ? `。構成銘柄は ${state.latest!.constituentsAsOf} 時点` : ''}</p>
    {state.latest!.epsJumped && <p className="lm-note lm-jump">この朝はEPSが前日から3%以上動きました（線が飛んでいます）。</p>}
    <div className="lm-scroll"><table className="lm-table">
      <thead><tr><th>価格（円）</th><th>前日終値との差</th><th>この価格の意味</th><th>山・谷ができた頻度</th><th>10営業日以内に届いた</th><th>到達までの日数</th></tr></thead>
      <tbody>
        {state.latest.rows.filter(r => r.side === 'UP').sort((a,b) => b.price-a.price).map((row, i) => <Row key={`u${i}`} row={row} />)}
        <tr className="lm-now"><td>{yen(state.latest!.previousClose)}</td><td colSpan={5}>前日終値</td></tr>
        {state.latest.rows.filter(r => r.side === 'DOWN').sort((a,b) => b.price-a.price).map((row, i) => <Row key={`d${i}`} row={row} />)}
      </tbody>
    </table></div>
    <p className="lm-guides">距離の目安 上 +1/+2/+3ATR: {state.latest!.atrGuides.UP.map(yen).join(' / ')}　下 −1/−2/−3ATR: {state.latest!.atrGuides.DOWN.map(yen).join(' / ')}</p>
    <p className="lm-small">「過去の頻度」は、その距離にある水準について、次の4%の転換点がその±1%に来た過去の頻度の帯です（2割前後・1〜2割・1割未満）。</p>
    <ul className="lm-fixed">{state.latest!.fixedNotesJa.map((note, i) => <li key={i}>{note}</li>)}</ul>
    </details>
    <details className="lm-records"><summary>PER線の答え合わせ・過去の記録</summary>
    {state.missedMornings.length > 0 && <p className="lm-small">寄付前に作れなかった朝: {state.missedMornings.join('、')}（後から作り直していません）</p>}
    {state.score && <Tally score={state.score} title={`答え合わせ（${state.score.firstMorning ?? ''}からの事前記録）`} />}
    {state.score && state.score.mornings < 60 && <p className="lm-small">件数が少ないうちは、成績として判断に使いません。精度の評価は数か月単位です。</p>}
    {state.retrospective && state.retrospective.mornings > 0 && <details className="lm-retro">
      <summary>後から数えた分（{state.retrospective.firstMorning}〜・判定には使いません）</summary>
      <Tally score={state.retrospective} title="後から数えた分" />
    </details>}
    </details>
  </section>;
}

/** Today: the five-session comparison reply carries the stored morning map. */
export function LevelMapCard() {
  const state = useJapanMarketComparison(5);
  if (!state.levelMap?.latest) return <section className="lm-card card" aria-label="日経平均の価格の目盛り">
    <header className="lm-heading"><b>日経平均の価格の目盛り</b></header>
    <p role="status">{state.loading ? '朝の保存データを読み込んでいます' : state.levelMapError ? '朝の保存データを読み込めませんでした' : '朝の価格と利益のデータを準備しています'}</p>
    {state.levelMapError && <button type="button" onClick={state.retry}>再取得</button>}
  </section>;
  return <><LevelMapView state={state.levelMap} />{state.levelMapError && <p role="status">更新できなかったため、保存済みの目盛りを表示しています。</p>}</>;
}
