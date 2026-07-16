import React from 'react';
import type { DeskCardData } from './types';
import { linkedTagJa } from './deskFormat';

// V12.2.12 — EVENTS & CATALYSTS(§7-6)。関連イベント全件(閉じたカードは2件
// まで)+材料ノート。イベントは既存の重要イベント連携(linkedAssets)そのまま。

export const AssetEventsPanel: React.FC<{ d: DeskCardData }> = ({ d }) => {
  if (d.eventTags.length === 0 && !d.strat.catalystNoteJa) {
    return <p className="uac-next" style={{ margin: 0, color: 'var(--text-faint)' }}>直近の関連イベント・材料の紐付けはありません。</p>;
  }
  return (
    <>
      {d.eventTags.length > 0 && (
        <p className="uac-next" style={{ marginBottom: 4 }}>
          {d.eventTags.map((le) => (
            <span key={`${le.code}-${le.countdown}`} className="ad-event" title="関連イベント">{linkedTagJa(le)}</span>
          ))}
        </p>
      )}
      {d.strat.catalystNoteJa && (
        <p className="uac-next" style={{ marginBottom: 0 }}>
          <span className="asset-detail__k" style={{ marginRight: 6 }}>Catalyst</span>
          <span style={{ color: 'var(--text-sub)' }}>{d.strat.catalystNoteJa}</span>
        </p>
      )}
    </>
  );
};
