import React from 'react';
import { useJapanEquityCalendar } from '../../hooks/useJapanEquityCalendar';
import { equityEventDistance, equityEventWhen } from '../../lib/japanEquityCalendar';
import './EquityEventList.css';

const MARK = { high: '重要', medium: '注意', low: '参考' } as const;

/** Every upcoming event with what it does to the Nikkei and the bull/bear ETFs (owner 2026-10-02). */
export function EquityEventList() {
  const calendar = useJapanEquityCalendar();
  const events = calendar.data?.events ?? [];
  if (!events.length && calendar.loading) return null;
  return <div className="equity-events" data-argus-contract="equity-event-calendar-v1">
    <b className="equity-events__head">日本株のイベント(だから何?つき)</b>
    {!events.length && <p className="equity-events__empty">{calendar.failed ? 'イベント日程を取得できていません(予定がないという意味ではありません)' : '45日以内の予定はありません'}</p>}
    {events.slice(0, 12).map(event => <details key={event.eventId} className={`equity-events__row is-${event.importance}`}
      data-event-kind={event.kind}>
      <summary>
        <span className="equity-events__when">{equityEventWhen(event)}<small>{equityEventDistance(event)}</small></span>
        <span className="equity-events__title"><b>{event.titleJa}</b><small>{event.soWhatJa.split('。')[0]}。</small></span>
        <span className={`equity-events__mark is-${event.importance}`}>{MARK[event.importance]}</span>
      </summary>
      <dl>
        <dt>何が起きる?</dt><dd>{event.whatJa}</dd>
        <dt>だから?</dt><dd>{event.soWhatJa}</dd>
        <dt>見るところ</dt><dd>{event.watchJa}</dd>
        {event.pastTendencyJa && <><dt>過去の傾向</dt><dd>{event.pastTendencyJa}</dd></>}
      </dl>
    </details>)}
    {calendar.data?.gaps.some(gap => gap.startsWith('jp_macro_schedule_not_published')) &&
      <p className="equity-events__note">これより先の日本の指標の公表予定は、まだ公式に発表されていないため未登録です。</p>}
  </div>;
}
