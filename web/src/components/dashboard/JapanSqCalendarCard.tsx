import React from 'react';
import { useJapanSqCalendar } from '../../hooks/useJapanSqCalendar';
import { sqCalendarIsCurrent } from '../../lib/japanSqCalendar';
import './JapanSqCalendarCard.css';
const STAGE = { TODAY: '本日SQ', LAST_TRADING_DAY: '本日が最終取引日', EVENT_WEEK: '今週はSQ', UPCOMING: '予定' };
export const JapanSqCalendarCard: React.FC = () => {
  const { data, loading, failed, checkedAt, retry } = useJapanSqCalendar();
  const current = sqCalendarIsCurrent(data, checkedAt);
  React.useEffect(() => {
    const focus = () => {
      const match = /^#notifications\/sq\/(jp-monthly-sq-\d{4}-\d{2})$/.exec(window.location.hash);
      const item = match && document.getElementById(match[1]);
      if (item instanceof HTMLDetailsElement) { item.open = true; item.scrollIntoView({block:'start'}); }
    };
    focus(); window.addEventListener('hashchange',focus);
    return () => window.removeEventListener('hashchange',focus);
  }, [data]);
  return <section className="jp-sq card" aria-label="SQ・30日先の予定">
    <div className="jp-sq__head"><h2>SQ・30日先の予定</h2><span>日本市場</span></div>
    {loading && !data && <p role="status">公式日程を確認しています…</p>}
    {failed && <p role="status">日程の更新を確認できません。{data?.events.length ? '最後に取得した予定を表示しています。' : '予定なしという意味ではありません。'}
      <button type="button" onClick={retry}>再読込</button></p>}
    {data && !current && <p role="status">日程の最終確認 {data.asOf}。接近日数・本日の案内は更新待ちです。</p>}
    {data?.status === 'PARTIAL' && <p>一部期間の公式日程または営業日を確認できていません。</p>}
    {data?.events.map(event => <details key={event.eventId} id={event.eventId} className="jp-sq__event">
      <summary><span className="jp-sq__title">{event.title} <time>{event.sqDate}</time></span>
        <span>{current && !failed ? STAGE[event.stage] : '保存済み予定'} · 詳細</span></summary>
      <div className="jp-sq__detail">
        <p>{event.summary}</p>
        <dl><dt>最終取引日</dt><dd>{event.lastTradingDate} 日中取引まで</dd>
          <dt>SQ算出日</dt><dd>{event.sqDate} 日本時間・構成銘柄の始値に基づく算出</dd>
          <dt>営業日</dt><dd>{current && !failed && event.calendarStatus === 'VERIFIED'
            ? `算出日まで ${event.tradingSessionsUntil} 営業日` : '接近日数を確認中'}</dd></dl>
        <p>金利・VIX・需給と実際の値動きを合わせて確認します。</p>
        <a href={event.sourceRef} target="_blank" rel="noreferrer">JPXの公式日程を見る ↗</a>
        <p className="jp-sq__source">資料取得 {event.knownAt}</p>
      </div>
    </details>)}
    {data?.status === 'AVAILABLE' && !failed && current && !data.events.length && <p>確認した30日先までの範囲にSQの予定はありません。</p>}
    <p className="jp-sq__source">予定はAI解析とは独立して表示します。</p>
  </section>;
};


export const JapanSqApproachNotice: React.FC = () => {
  const { data, failed, checkedAt } = useJapanSqCalendar();
  if (failed || !sqCalendarIsCurrent(data, checkedAt)) return null;
  const approaching = data?.events.find(event => event.calendarStatus === 'VERIFIED' && event.stage !== 'UPCOMING');
  if (!approaching) return null;
  const openDetails = () => {
    const element = document.getElementById(approaching.eventId);
    if (element instanceof HTMLDetailsElement) element.open = true;
    element?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  return <aside className="jp-sq-approach" aria-label="接近するSQの案内">
    <div><b>{STAGE[approaching.stage]} · {approaching.title}</b>
      <p>{approaching.sqDate} 算出 · 最終取引 {approaching.lastTradingDate} 日中まで</p>
      <small>清算に関係する日程です。金利・需給・実際の値動きと合わせて確認します。</small></div>
    <button type="button" onClick={openDetails}>日程の詳細</button>
  </aside>;
};
