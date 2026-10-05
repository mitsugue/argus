import React from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { evidenceJa, rowLabelJa, type LevelMapRow, type LevelMapScore, type LevelMapState } from '../../lib/levelMap';
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
  const map = state?.latest;
  if (!state || !map) return null;
  const up = map.rows.filter(r => r.side === 'UP').sort((a, b) => b.price - a.price);
  const down = map.rows.filter(r => r.side === 'DOWN').sort((a, b) => b.price - a.price);
  const cov = map.epsCoverage;
  const perRows = map.rows.filter(r => r.kinds.includes('PER_LINE'));
  const above = perRows.filter(r => r.side === 'UP').sort((a, b) => a.price - b.price)[0];
  const below = perRows.filter(r => r.side === 'DOWN').sort((a, b) => b.price - a.price)[0];
  const examples = [above && `${yen(above.price)}円まで上がると${above.multiple}倍`,
    below && `${yen(below.price)}円まで下がると${below.multiple}倍`].filter(Boolean);
  const distances = [above && `上の目印までは${signed(above.distancePct)}%`,
    below && `下の目印までは${signed(below.distancePct)}%`].filter(Boolean);
  return <section className="lm-card card" aria-label="日経平均の価格の目盛り" data-argus-contract="level-map-v1"
    data-morning={map.morningOf}>
    <header className="lm-heading"><b>日経平均の価格の目盛り</b><span>PER · {map.morningOf.slice(5).replace('-', '/')}朝の保存値</span></header>
    <div className="lm-reading">
      <p>この表は、<strong>企業の利益に対して、日経平均が何倍の値段になっているか</strong>を示す目盛りです。</p>
    </div>
    <div className="lm-price-ladder" aria-label="価格と利益の倍率">
      {above && <article data-side="UP"><span>{above.multiple}倍まで上がると</span><b>{yen(above.price)}<small>円</small></b><strong>{signed(above.distancePct)}%</strong></article>}
      <article data-side="NOW"><span>前日終値 · {map.per.toFixed(2)}倍</span><b>{yen(map.previousClose)}<small>円</small></b><small>{map.previousSession.slice(5).replace('-', '/')}の終値</small></article>
      {below && <article data-side="DOWN"><span>{below.multiple}倍まで下がると</span><b>{yen(below.price)}<small>円</small></b><strong>{signed(below.distancePct)}%</strong></article>}
    </div>
    <p className="lm-use">チャートのPER線と同じ目盛りです。値動きを、企業の利益に対する価格の大きさで比べられます。</p>
    <details className="lm-explanation"><summary>倍率と価格の読み方</summary>
      <p>たとえば、この朝は約{map.per.toFixed(2)}倍。{examples.length > 0 && `日経平均が${examples.join('、')}になります。`}</p>
      {distances.length > 0 && <p>前日終値 {yen(map.previousClose)}円から、{distances.join('、')}です。</p>}
      <small>株価が動いた時の位置を確かめる表です。ここで反転するかは未確認のため、売買時期の判断には使えません。</small>
    </details>
    <details className="lm-all-levels"><summary>すべての価格・計算の根拠</summary>
    <p className="lm-note">{map.morningOf} 朝 · 寄付前に固定保存（{jst(map.createdAt)}）</p>
    <p className="lm-note">前日終値 {yen(map.previousClose)}（{map.previousSession}）· ATR14 {yen(map.atr14)} ·
      EPS {map.eps.toFixed(1)}（{map.epsDate}）· PER {map.per.toFixed(2)}倍</p>
    <p className="lm-note lm-eps">{map.epsLabelJa}{cov ? `。予想が無く実績で補った社 ${cov.filledFromTrailing ?? 0}・赤字予想 ${cov.negativeForecast ?? 0}` : ''}
      {map.constituentsAsOf ? `。構成銘柄は ${map.constituentsAsOf} 時点` : ''}</p>
    {map.epsJumped && <p className="lm-note lm-jump">この朝はEPSが前日から3%以上動きました（線が飛んでいます）。</p>}
    <div className="lm-scroll"><table className="lm-table">
      <thead><tr><th>価格（円）</th><th>前日終値との差</th><th>この価格の意味</th><th>山・谷ができた頻度</th><th>10営業日以内に届いた</th><th>到達までの日数</th></tr></thead>
      <tbody>
        {up.map((row, i) => <Row key={`u${i}`} row={row} />)}
        <tr className="lm-now"><td>{yen(map.previousClose)}</td><td colSpan={5}>前日終値</td></tr>
        {down.map((row, i) => <Row key={`d${i}`} row={row} />)}
      </tbody>
    </table></div>
    <p className="lm-guides">距離の目安 上 +1/+2/+3ATR: {map.atrGuides.UP.map(yen).join(' / ')}　下 −1/−2/−3ATR: {map.atrGuides.DOWN.map(yen).join(' / ')}</p>
    <p className="lm-small">「過去の頻度」は、その距離にある水準について、次の4%の転換点がその±1%に来た過去の頻度の帯です（2割前後・1〜2割・1割未満）。</p>
    <ul className="lm-fixed">{map.fixedNotesJa.map((note, i) => <li key={i}>{note}</li>)}</ul>
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
  return <LevelMapView state={state.levelMap} />;
}
