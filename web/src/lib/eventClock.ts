// ARGUS v12.0.8追補 — 単一のイベント時計。
// 右上Nextチップ・下部スティッキーバー・Session Brief等が「次のイベント」を
// 選ぶ時は必ずここを通る: 日時がパースできる未来のイベントだけが対象で、
// 発表済(過去)・日付不明のイベントは絶対に「次」にならない。
// 表示は必ず 日付+JST時刻+D-count(時刻だけの表示は禁止 — CPI 7/14事件の根治)。

import type { ImportantEvent } from '../hooks/useImportantEvents';

export interface NextEventPick {
  eventCode: string;
  title: string;
  dateJa: string;      // "7/14"
  timeJa: string;      // "21:30 JST" or ''
  daysUntil: number;   // 0=本日
  labelJa: string;     // "CPI 7/14 21:30 JST · あと7日"
  shortJa: string;     // スティッキーバー用 "CPI 7/14 · あと7日"
}

function eventEpoch(e: ImportantEvent): number | null {
  // jstTime: "YYYY-MM-DD HH:MM JST" / date: "YYYY-MM-DD"
  const jt = e.jstTime ? String(e.jstTime).replace(' JST', '').replace(' ', 'T') + ':00+09:00' : null;
  const cand = jt ?? (e.date ? `${e.date}T23:59:00+09:00` : null);
  if (!cand) return null;
  const t = Date.parse(cand);
  return Number.isFinite(t) ? t : null;
}

/** 未来(本日を含む)の、日時がパースできるイベントだけから次の1件を選ぶ。 */
export function nextUpcomingEvent(events: ImportantEvent[], nowMs: number,
                                  opts?: { highImpactOnly?: boolean }): NextEventPick | null {
  const todayStartJst = (() => {
    const d = new Date(nowMs);
    const jstDay = d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Tokyo' }); // YYYY-MM-DD
    return Date.parse(`${jstDay}T00:00:00+09:00`);
  })();
  const cands = (events ?? [])
    .filter((e) => !opts?.highImpactOnly || e.displayImpact === 'high' || e.displayImpact === 'critical')
    .map((e) => ({ e, t: eventEpoch(e) }))
    .filter((x): x is { e: ImportantEvent; t: number } => x.t != null && x.t >= todayStartJst)
    .filter((x) => x.e.countdown !== 'D+1' && x.e.lifecycle !== 'RELEASED' && x.e.lifecycle !== 'RESOLVED')      // 発表済は「次」にしない
    .sort((a, b) => a.t - b.t);
  const top = cands[0];
  if (!top) return null;
  const d = new Date(top.t);
  const md = d.toLocaleDateString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' });
  const hm = top.e.jstTime ? d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' }) + ' JST' : '';
  const days = Math.round((Date.parse(d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Tokyo' }) + 'T00:00:00+09:00') - todayStartJst) / 86_400_000);
  const rel = days === 0 ? '本日' : `あと${days}日`;
  return {
    eventCode: top.e.eventCode, title: top.e.title,
    dateJa: md, timeJa: hm, daysUntil: days,
    labelJa: `${top.e.eventCode} ${md}${hm ? ` ${hm}` : ''} · ${rel}`,
    shortJa: `${top.e.eventCode} ${md} · ${rel}`,
  };
}
