import React from 'react';
import { EventImpactBadge } from './EventImpactBadge';
import { useJapanEquityCalendar } from '../../hooks/useJapanEquityCalendar';
import type { DashboardEventsResponse,DashboardEvent } from '../../lib/dashboardEventState';
import type { ImportantEvent } from '../../hooks/useImportantEvents';
import { equityEventWhen,equityEventDistance } from '../../lib/japanEquityCalendar';
import { todayEventSchedule, prominentResult } from '../../lib/todayEventSchedule';

export function TodayEventSchedule({dashboard,legacy,sectionId,renderDashboard,renderLegacy}:{
  dashboard:DashboardEventsResponse|null;legacy:ImportantEvent[];sectionId:string;
  renderDashboard:(e:DashboardEvent)=>React.ReactNode;renderLegacy:(e:ImportantEvent)=>React.ReactNode;
}) {
  const calendar=useJapanEquityCalendar();
  const rows=todayEventSchedule(dashboard?.items??[],legacy,calendar.data?.events??[]);
  const recent=rows.filter(e=>prominentResult(e)),upcoming=rows.filter(e=>!e.released),released=rows.filter(e=>e.released&&!prominentResult(e));
  const render=(row:typeof rows[number]) => row.kind==='dashboard'?renderDashboard(row.event)
    :row.kind==='legacy'?renderLegacy(row.event):<article className="te-equity" data-impact={row.event.importance}>
      <div className="te-when">{equityEventWhen(row.event)} · {equityEventDistance(row.event)}</div>
      <div className="te-title"><h4>{row.event.titleJa}</h4><EventImpactBadge impact={row.event.importance} /></div>
      <p>{row.event.soWhatJa}</p>
      <details><summary>詳しく</summary><p>{row.event.whatJa}</p><p>{row.event.watchJa}</p>
        {row.event.pastTendencyJa&&<p>{row.event.pastTendencyJa}</p>}<small>出典：{row.event.source}</small></details>
    </article>;
  return <section id={sectionId} className="te-schedule" aria-label="日付順のイベント">
    {!dashboard?.items.length&&!legacy.length&&<p role="status">米国の予定: 取得できません</p>}
    {calendar.failed&&<p role="status">日本の予定: 更新失敗・保存分</p>}
    {calendar.data?.gaps.length? <p role="status">一部の予定は公式日程未確認</p>:null}
    {!rows.length&&<p>{calendar.loading?'読み込み中':'取得できません'}</p>}
    {recent.length>0&&<div className="te-recent"><h4>直近の結果・発表後48時間</h4>
      {recent.map(row=><React.Fragment key={row.key}>{render(row)}</React.Fragment>)}</div>}
    <div>{upcoming.map(row=><React.Fragment key={row.key}>{render(row)}</React.Fragment>)}</div>
    {released.length>0&&<details className="te-released" open><summary>直近の発表結果・市場の反応</summary>
      {released.map(row=><React.Fragment key={row.key}>{render(row)}</React.Fragment>)}</details>}
  </section>;
}
