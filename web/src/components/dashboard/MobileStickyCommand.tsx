import React from 'react';
import { createPortal } from 'react-dom';
import './MobileStickyCommand.css';

// V11.21.0 — モバイル専用の下部コンパクトバー(720px以下のみ表示)。
// 10秒把握の核: 今日のモード / P0件数 / 次イベント / 未読通知。
// 控えめ(高さ~36px)・コンテンツを隠さない(ページ側にspacerあり)。
// NOTE: AppShellのページ遷移transformがfixedの基準を奪うため、バー本体は
// portalでdocument.body直下に描画する(spacerはページ内)。

export const MobileStickyCommand: React.FC<{
  ownerModeJa: string;
  p0Count: number;
  nextEventJa: string | null;
  unreadCount: number;
}> = ({ ownerModeJa, p0Count, nextEventJa, unreadCount }) => (
  <>
    <div className="msc-spacer" aria-hidden />
    {createPortal(
      <div className="msc" role="status" aria-label="今日の要約バー">
        <span className="msc__mode">{ownerModeJa}</span>
        <span className={`msc__p0 ${p0Count > 0 ? 'is-hot' : ''}`}>
          {p0Count > 0 ? `P0×${p0Count}` : 'P0なし'}
        </span>
        {nextEventJa && <span className="msc__ev">{nextEventJa}</span>}
        {unreadCount > 0 && <span className="msc__bell">🔔{unreadCount}</span>}
      </div>,
      document.body,
    )}
  </>
);

export default MobileStickyCommand;
