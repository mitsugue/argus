import React from 'react';
import { CollapsibleSection, resetTodayLayout } from '../common/CollapsibleSection';
import './Today.css';

// V12.2.11 — Details / Deep Dive: ファーストビュー以外を役割別5グループへ。
// 初期状態は閉じる(criticalはCollapsibleSectionのdefaultOpenが安全側で開く)。
// 中身は既存セクションをそのまま受け取る(データ配線・publishはCommandCenter側)。

export interface DetailGroup {
  title: string;
  persistKey: string;
  countLabel?: string;
  conclusionJa?: string;
  severityTone?: string;
  defaultOpen?: boolean;
  render: () => React.ReactNode;
}

export const TodayDetails: React.FC<{
  groups: DetailGroup[];
}> = ({ groups }) => (
  <div className="tdetails">
    <p className="tdetails__caption">DETAILS / DEEP DIVE</p>
    {groups.map((g) => (
      <CollapsibleSection key={g.persistKey} title={g.title} persistKey={g.persistKey}
        countLabel={g.countLabel} conclusionJa={g.conclusionJa}
        severityTone={g.severityTone} defaultOpen={g.defaultOpen}>
        {g.render}
      </CollapsibleSection>
    ))}
    <p className="tdetails__note" style={{ textAlign: 'right' }}>
      <button type="button"
        onClick={() => { resetTodayLayout(); window.location.reload(); }}
        style={{ fontSize: 10, color: 'var(--text-faint)', background: 'transparent',
                 border: 'none', cursor: 'pointer', textDecoration: 'underline',
                 minHeight: 32 }}>
        セクションの開閉状態をリセット
      </button>
    </p>
  </div>
);
