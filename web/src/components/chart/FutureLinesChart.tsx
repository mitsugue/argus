import React, { useEffect, useRef, useState } from 'react';
import { useFutureLines } from '../../hooks/useFutureLines';
import { LINE_LABEL, MEASURE_LABEL, dayNumber, linesFrame, nextTurn, pathPoints, scoreJa, type FutureLinesDoc, type LineId, type LineRecord } from '../../lib/futureLines';
import './NikkeiResearchChart.css';
import './FutureLinesChart.css';

const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
const md = (date: string) => `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`;
const KIND = { H: '山', L: '谷' } as const;
/** First day of each month inside the drawing window, as YYYY-MM-01. */
function months(start: number, end: number) {
  const out: string[] = [];
  const d = new Date(start); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + 1);
  while (d.getTime() <= end && out.length < 12) { out.push(d.toISOString().slice(0, 10)); d.setUTCMonth(d.getUTCMonth() + 1); }
  return out;
}
// 2026-10-26 (owner): the chart shows the video's line only. The two machine
// lines stay in the weekly record as yardsticks (one line in the fold).
const IDS: LineId[] = ['commentator'];

function RecordTable({ id, record, retro }: { id: LineId; record?: LineRecord; retro?: LineRecord }) {
  const rows = (['strict', 'standard', 'loose', 'timing'] as const);
  return <div className="fl-record" data-argus-contract="future-lines-record-v1">
    <b>{LINE_LABEL[id]}の成績（事前に記録した分）</b>
    {!record || !record.records ? <p>記録なし</p> : <>
      <table><thead><tr><th>物差し</th><th>当たり</th><th>判定待ち</th><th>でたらめな予想</th></tr></thead>
        <tbody>{rows.map(m => { const x = record[m]; return <tr key={m}><td>{MEASURE_LABEL[m]}</td>
          <td>{x ? `${x.hit}/${x.n}` : '―'}</td><td>{x ? x.pending : '―'}</td><td>{x && x.n && x.randomMean !== null ? `平均${x.randomMean}` : '―'}</td></tr>; })}</tbody></table>
      <p>最初の点に、逆へ5%動く前に届いたか：届いた {record.reach.reach}・崩れた {record.reach.stop}・期限切れ {record.reach.expire}・判定待ち {record.reach.pending}（記録 {record.records}件）</p>
    </>}
    {retro && retro.loose && <p className="fl-retro">後から読み取った分：ゆるい {retro.loose.hit}/{retro.loose.n}（でたらめ平均{retro.loose.randomMean ?? '―'}）・標準 {retro.standard?.hit ?? '―'}/{retro.standard?.n ?? '―'}</p>}
  </div>;
}

export function FutureLinesChartView({ doc }: { doc: FutureLinesDoc }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(390);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.round(entry.contentRect.width))));
    observer.observe(el); return () => observer.disconnect();
  }, []);
  const ids = IDS;
  const frame = linesFrame(doc, ids);
  const left = 8, right = width - 76, top = 22, bottom = 250;
  const x = (date: string) => left + (dayNumber(date) - frame.start) / Math.max(1, frame.end - frame.start) * (right - left);
  const y = (v: number) => top + (frame.high - v) / Math.max(1, frame.high - frame.low) * (bottom - top);
  const line = (pts: { date: string; price: number }[]) => pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.date).toFixed(1)},${y(p.price).toFixed(1)}`).join(' ');
  const wave = doc.wave && !doc.wave.settledBeforeRecord ? doc.wave : null;
  const latest = frame.shown.filter(s => s.latest);
  const lastClose = frame.closes.at(-1);
  return <div className="nr-chart fl-chart" ref={ref} data-argus-contract="future-lines-chart-v1">
    {!latest.length && <p role="status">記録なし</p>}
    <div className="nr-plot-wrap"><svg viewBox={`0 0 ${width} ${bottom + 32}`} role="img" aria-label={`日経平均の終値と${ids.map(i => LINE_LABEL[i]).join('・')}`}>
      {frame.multiples.map(m => <g key={m} className="nr-per-label"><line x1={left} x2={right + 4} y1={y(frame.eps! * m)} y2={y(frame.eps! * m)} />
        <text x={right + 6} y={y(frame.eps! * m) + 3}>PER{m} {yen(frame.eps! * m)}円</text></g>)}
      {frame.closes.length > 1 && <path className="nr-price" d={line(frame.closes.map(c => ({ date: c.date, price: c.close })))} />}
      {wave && <g className="fl-wave">
        <line className="nr-target" x1={x(wave.pub)} x2={right} y1={y(wave.target)} y2={y(wave.target)} />
        <line className="nr-stop" x1={x(wave.pub)} x2={right} y1={y(wave.stop)} y2={y(wave.stop)} />
        <text x={x(wave.pub) + 2} y={y(wave.target) - 4}>波動の公開予想の目標 {yen(wave.target)}円</text>
        <text x={x(wave.pub) + 2} y={y(wave.stop) + 11}>崩れの水準 {yen(wave.stop)}円</text></g>}
      {frame.shown.filter(s => !s.latest).map((s, i) => <path key={`old-${s.id}-${i}`} className={`fl-line fl-${s.id} is-old`} d={line(pathPoints(s.line, frame.closes))} />)}
      {latest.map(s => <g key={s.id} className={`fl-${s.id}`}>
        <path className="fl-line" d={line(pathPoints(s.line, frame.closes))} />
        {/* 2026-10-25 (owner): one labelled line keeps the chart readable; the
            table below names every line's next turning point. */}
        {s.line.points.map((p, i) => <g key={i}><circle className="fl-point" cx={x(p.date)} cy={y(p.price)} r={s.id === 'commentator' ? 3.5 : 2.5} />
          {s.id === 'commentator' && <text className="fl-point-label" x={x(p.date)} y={p.kind === 'H' ? y(p.price) - 7 : y(p.price) + 14} textAnchor="middle">{KIND[p.kind]} {md(p.date)}</text>}</g>)}
      </g>)}
      {months(frame.start, frame.end).map(m => <g key={m} className="nr-grid"><line x1={x(m)} x2={x(m)} y1={top} y2={bottom} />
        <text x={x(m) + 2} y={bottom + 12}>{Number(m.slice(5, 7))}月</text></g>)}
      {lastClose && <><line className="nr-today" x1={x(lastClose.date)} x2={x(lastClose.date)} y1={top} y2={bottom} />
        <text className="nr-today-label" x={x(lastClose.date)} y={bottom + 24} textAnchor="middle">{md(lastClose.date)}の終値まで</text></>}
    </svg></div>
    <div className="nr-legend"><span className="nr-key-price">日経平均</span>
      {ids.map(id => <span key={id} className={`fl-key fl-${id}`}>{LINE_LABEL[id]}（毎週の山・谷の予想）</span>)}
      {wave && <span>波動の目標・崩れ</span>}
      {/* 2026-10-25 (owner): the line styles are read without opening the details. */}
      <span className="fl-key-style">実線＝今週・点線＝前の週</span></div>
    {latest.length > 0 && <div className="fl-next" data-argus-contract="future-lines-next-v1">
      <p className="nr-note">次の転換点（{md(latest[0].line.rec)}の終値まで・毎週土曜に更新）</p>
      <table><thead><tr><th>線</th><th>次</th><th>目安</th><th>成績</th></tr></thead>
        <tbody>{latest.map(s => { const next = nextTurn(s.line, [doc.dataEnd, lastClose?.date ?? ''].sort().at(-1)!); return <tr key={s.id}>
          <td><b className={`fl-${s.id}`}>{LINE_LABEL[s.id]}</b></td>
          <td>{next ? `${KIND[next.kind]} ${md(next.date)}` : '―'}</td><td>{next ? `${yen(next.price)}円` : '―'}</td>
          <td className="fl-score">{scoreJa(doc.record[s.id])}</td></tr>; })}</tbody></table>
      {wave && <p className="nr-note">波動の公開予想（{md(wave.pub)}）：{wave.dir === 'up' ? '上向き' : '下向き'}・目標 {yen(wave.target)}円・崩れ {yen(wave.stop)}円 → {wave.result === 'pending' ? '判定待ち' : wave.result === 'reach' ? '届いた' : wave.result === 'stop' ? '崩れた' : '期限切れ'}</p>}
    </div>}
    <details className="fl-details"><summary>線の全部の点・成績の詳しい見方</summary>
      <div className="fl-points">{latest.map(s => <p key={s.id}><b className={`fl-${s.id}`}>{LINE_LABEL[s.id]}</b>（{md(s.line.rec)}の大引けまでで記録）：
        {s.line.points.map(p => `${KIND[p.kind]} ${md(p.date)} ${yen(p.price)}円`).join(' → ')}</p>)}</div>
      <p className="nr-note">動画の線＝動画で示された予想の線・2018年の暦＝2018年の同じ月日の山谷・山谷の間隔＝直近の山谷の間隔。実線が今週、点線が前の週。</p>
      {ids.map(id => <RecordTable key={id} id={id} record={doc.record[id]} retro={doc.retroRecord[id]} />)}
      <p className="nr-note">{doc.record.wave && doc.record.wave.records
        ? `波動の公開予想の成績（目標に崩れより先に届いたか）：届いた ${doc.record.wave.reach}/${doc.record.wave.n}・判定待ち ${doc.record.wave.pending}（記録 ${doc.record.wave.records}件）`
        : '波動の公開予想：記録なし'}</p>
      <p className="nr-note">比べる物差し（2018年の暦・山谷の間隔）は、2010〜2025年の検証で日付の当たりがでたらめと同じ</p>
      <p className="nr-note">記録 {doc.updatedAt.slice(0, 16).replace('T', ' ')}・価格 {md(doc.dataEnd)}まで</p>
    </details>
  </div>;
}

export function FutureLinesChart() {
  const state = useFutureLines();
  if (!state.doc) return <p role="status">{state.status === 'loading' ? '読み込み中' : '取得できません'}</p>;
  return <FutureLinesChartView doc={state.doc} />;
}
