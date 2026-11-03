import React from 'react';
import { createPortal } from 'react-dom';
import { jumpTo } from '../../lib/todayJump';
import './MobileStickyCommand.css';

// V11.21.0 — モバイル専用の下部コンパクトバー(720px以下のみ表示)。
// 既存のイベント日程と残り時間。売買判断は表示しない。
// 控えめ(高さ~36px)・コンテンツを隠さない(ページ側にspacerあり)。
// NOTE: AppShellのページ遷移transformがfixedの基準を奪うため、バー本体は
// portalでdocument.body直下に描画する(spacerはページ内)。

type StickyEvent = { name: string; when: string; remaining: string | null };
type Props = { text:string; event?:StickyEvent|null; events?:StickyEvent[] };

// Owner request 2026-10-23: tapping the next event opens Today's EVENTS block, the same move as the tiles.
// The bar is shown on Today only (MobileStickyCommand.css gates it by route), so no page switch is needed.
export const MobileStickyBar: React.FC<Props> = ({ text, event, events }) => {
  const shown = events?.length ? events.slice(0,3) : event ? [event] : [];
  return <div className="msc" role="status" aria-label="次のイベント" title={text} data-event-count={shown.length}>
    {shown.length ? shown.map((event,index)=><button key={`${event.name}:${event.when}`} type="button" className="msc__jump" onClick={() => jumpTo('today-events')}
      title={`${event.name} · ${event.when}${event.remaining ? ` · ${event.remaining}` : ''}`}
      aria-label={`次のイベント ${event.name}、${event.when}${event.remaining ? `、${event.remaining}` : ''}。予定の一覧へ移る`}>
      <span className="msc__name">{index===0?'次: ':''}{event.name}</span>
      <span className="msc__when">{event.when}{event.remaining && ` · ${event.remaining}`}</span>
    </button>) : <span className="msc__name">{text}</span>}
  </div>;
};

export const MobileStickyCommand: React.FC<Props> = ({ text, event, events }) => (
  <>
    <div className="msc-spacer" aria-hidden />
    {createPortal(<MobileStickyBar text={text} event={event} events={events} />, document.body)}
  </>
);

export default MobileStickyCommand;
