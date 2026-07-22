import React from 'react';
import { createPortal } from 'react-dom';
import './MobileStickyCommand.css';

// V11.21.0 — モバイル専用の下部コンパクトバー(720px以下のみ表示)。
// 10秒把握の核: Todayの単一view modelが生成した短い判断要約。
// 控えめ(高さ~36px)・コンテンツを隠さない(ページ側にspacerあり)。
// NOTE: AppShellのページ遷移transformがfixedの基準を奪うため、バー本体は
// portalでdocument.body直下に描画する(spacerはページ内)。

export const MobileStickyCommand: React.FC<{
  text: string;
}> = ({ text }) => (
  <>
    <div className="msc-spacer" aria-hidden />
    {createPortal(
      <div className="msc" role="status" aria-label="今日の要約バー">
        <span className="msc__mode">{text}</span>
      </div>,
      document.body,
    )}
  </>
);

export default MobileStickyCommand;
