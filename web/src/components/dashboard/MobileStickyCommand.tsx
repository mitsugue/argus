import React from 'react';
import { createPortal } from 'react-dom';
import './MobileStickyCommand.css';

// V11.21.0 — モバイル専用の下部コンパクトバー(720px以下のみ表示)。
// 既存のイベント日程と残り時間。売買判断は表示しない。
// 控えめ(高さ~36px)・コンテンツを隠さない(ページ側にspacerあり)。
// NOTE: AppShellのページ遷移transformがfixedの基準を奪うため、バー本体は
// portalでdocument.body直下に描画する(spacerはページ内)。

export const MobileStickyCommand: React.FC<{
  text: string;
  event?: { name: string; when: string; remaining: string | null } | null;
}> = ({ text, event }) => (
  <>
    <div className="msc-spacer" aria-hidden />
    {createPortal(
      <div className="msc" role="status" aria-label="次のイベント" title={text}>
        {event ? <>
          <span className="msc__name">次: {event.name}</span>
          <span className="msc__when">{event.when}{event.remaining && ` · ${event.remaining}`}</span>
        </> : <span className="msc__name">{text}</span>}
      </div>,
      document.body,
    )}
  </>
);

export default MobileStickyCommand;
