import React, { useEffect, useState } from 'react';
import { FUTURE_MAP_POLL_MS, useFutureMap, type FutureMapDoc, type FutureMapRow } from '../../hooks/useFutureMap';
import './FutureMapCard.css';

// FUTURE MAP (owner-approved 2026-10-04): a table of external views of the
// coming weeks, not ARGUS's judgment. No probability, no trading decision.
const md = (iso: string) => { const [, m, d] = iso.split('-'); return `${Number(m)}/${Number(d)}`; };
const yen = (v: number) => Math.round(v).toLocaleString('ja-JP');
const levelText = (row: FutureMapRow) => !row.level ? '―'
  : row.level.low === row.level.high ? yen(row.level.low) : `${yen(row.level.low)}〜${yen(row.level.high)}`;
const RESULT_JA = { reached: '到達', missed: '外れ' } as const;
const SCORE_WAIT_JA: Record<string, string> = { LATE_REGISTRATION: '事前記録なし・成績に含めません',
  PRICES_INCOMPLETE: '採点に必要な価格が不足', DIRECTION_NOT_DEFINED: '方向の採点規則なし' };

function sourceUpdateTimestamp(updatedAt: string) {
  const parts = typeof updatedAt === 'string'
    ? /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(updatedAt) : null;
  if (!parts || Number(parts[2]) > 23 || Number(parts[3]) > 59 || Number(parts[4]) > 59
    || Number(parts[6] ?? 0) > 23 || Number(parts[7] ?? 0) > 59) return NaN;
  const day = Date.parse(`${parts[1]}T00:00:00Z`);
  if (!Number.isFinite(day) || new Date(day).toISOString().slice(0, 10) !== parts[1]) return NaN;
  return Date.parse(updatedAt);
}

/** Source update age, never the time this browser fetched the table. */
export function futureMapUpdateAge(updatedAt: string, nowMs: number) {
  const stamp = sourceUpdateTimestamp(updatedAt);
  if (!Number.isFinite(stamp) || !Number.isFinite(nowMs) || stamp > nowMs) {
    return { days: null, warning: true, label: '更新日時を確認できません' };
  }
  const days = Math.floor((nowMs - stamp) / 86_400_000);
  return { days, warning: days >= 3,
    label: days >= 3 ? `${days}日前の更新・古い予測です`
      : days === 0 ? '24時間以内の更新' : `${days}日前の更新` };
}

function Row({ row }: { row: FutureMapRow }) {
  return <tr className={`fm-row${row.isNow ? ' is-now' : ''}${row.emphasis ? ' is-emphasis' : ''}${row.past ? ' is-past' : ''}`}
    data-row={row.id} data-tag={row.tag}>
    <td className="fm-period">{row.periodLabel}{row.isNow && <small className="fm-here">いまここ</small>}</td>
    <td className="fm-view">
      <span>{row.view}</span>{row.agree > 0 && <span className="fm-agree" aria-label={`同じ見立て ${row.agree}`}>{'●'.repeat(row.agree)}</span>}
      {row.changed && <small className="fm-changed">変</small>}
      {row.result && <small className={`fm-result is-${row.result}`}>{RESULT_JA[row.result]}</small>}
      {!row.result && row.scoringStatus && SCORE_WAIT_JA[row.scoringStatus] && <small className="fm-sub">{SCORE_WAIT_JA[row.scoringStatus]}</small>}
      {row.reason && <small className="fm-sub">{row.reason}</small>}
      {row.alt && <small className="fm-sub">別の見方: {row.alt}</small>}
    </td>
    <td className="fm-level">{levelText(row)}</td>
    <td className="fm-tagcell"><span className={`fm-tag tone-${row.tone}`}>{row.tag}</span></td>
  </tr>;
}

export function FutureMapView({ doc, nowMs }: { doc: FutureMapDoc | null; nowMs?: number }) {
  const [open, setOpen] = useState(false);
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const tick = () => { if (document.visibilityState === 'visible') setClock(Date.now()); };
    const timer = window.setInterval(tick, FUTURE_MAP_POLL_MS);
    document.addEventListener('visibilitychange', tick);
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', tick); };
  }, []);
  if (!doc || !doc.rows.length) return null;
  const age = futureMapUpdateAge(doc.updatedAt, nowMs ?? clock);
  const updatedStamp = sourceUpdateTimestamp(doc.updatedAt);
  const updateDate = Number.isFinite(updatedStamp) ? new Date(updatedStamp).toLocaleDateString('ja-JP',
    { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' }) : '―';
  const nowIndex = Math.max(0, doc.rows.findIndex(r => r.isNow));
  const lead = doc.rows.slice(nowIndex, nowIndex + 4);
  const shown = open ? doc.rows : lead;
  const hidden = doc.rows.length - lead.length;
  const goal = [...doc.rows].reverse().find(r => r.emphasis);
  const { position, nextAlert, nextBottom } = doc.status;
  return <section className="fm-card card" aria-label="FUTURE MAP" data-argus-contract="future-map-v1">
    <div className="fm-head"><b>FUTURE MAP</b>
      <span>外部の見立て ・ {updateDate}更新 ・ 予測が当たるかは未検証</span>
      <span className={`fm-age${age.warning ? ' is-warning' : ''}`} role={age.warning ? 'status' : undefined}>{age.label}</span></div>
    <div className="fm-boxes">
      <div className="fm-box tone-red"><small>いまの位置</small><b>{position}</b></div>
      <div className="fm-box tone-amber"><small>次の警戒日</small><b>{md(nextAlert.date)} {nextAlert.label}</b></div>
      <div className="fm-box tone-green"><small>次の買い場</small><b>{nextBottom.label}</b></div>
    </div>
    <table className="fm-table">
      <thead><tr><th>時期</th><th>見立て</th><th>目安(円)</th><th>警戒</th></tr></thead>
      <tbody>{shown.map(row => <Row key={row.id} row={row} />)}</tbody>
    </table>
    {hidden > 0 && <button type="button" className="fm-more" aria-expanded={open} onClick={() => setOpen(v => !v)}>
      {open ? '閉じる' : `すべて表示（残り${hidden}件${goal ? `・${goal.periodLabel} ${goal.view.split('。')[0]}まで` : ''}）`}</button>}
    <p className="fm-foot">●の数 = 同じことを言っている見立ての数 ・ {doc.record.scored > 0
      ? `答え合わせ: ${doc.record.scored}件中${doc.record.reached}件到達${doc.record.scored < 10 ? '（件数不足）' : ''}` : '答え合わせ: 0件（まだ成績なし）'}</p>
    {doc.scoring && <details><summary>答え合わせの条件</summary>
      <p>水準つきは期日前後５営業日の価格±１％、方向だけは期間中の３％の動きを確認します。確認期間が終わり、全営業日の価格がそろってから採点します。</p>
      <p>最初に保存した予測だけを成績に数えます。事前記録がない行は除き、変更前の予測と結果は残します。価格到達は天井・底や売買の有効性の証明ではありません。</p>
      {doc.scoring.status === 'FAILED' && <p role="status">答え合わせの保存・計算を確認できません。前回の結果を表示しています。</p>}
    </details>}
  </section>;
}

export function FutureMapCard() {
  return <FutureMapView doc={useFutureMap()} />;
}
