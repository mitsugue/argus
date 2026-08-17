import React from 'react';
import type { TodayChangeView } from '../../domain/todayOverview';
import './Today.css';

// V12.2.11 — Overnight Changes: 「前回から何が変わったか」だけに答える(≤4件)。
// 比較元がある項目だけ矢印つき。イベントは方向予測ではなくリスクウィンドウ。

export const OvernightChangesCard: React.FC<{
  headingEn: string;
  changes: TodayChangeView[];
}> = ({ headingEn, changes }) => (
  <section className="tcard tg-span-7" aria-label="Changes since last check">
    <div className="tcard__head">
      <span className="tcard__title">{headingEn}</span>
    </div>
    <div className="tchg">
      {changes.map((c) => (
        <div className="tchg__row" key={c.id}>
          <span className="tchg__label">{c.labelEn}</span>
          <span className={`tchg__main${c.tone !== 'neutral' ? ` tchg__main--${c.tone}` : ''}`}>
            {c.mainJa}
            {c.asOfJa && <span className="tchg__asof">{c.asOfJa}</span>}
          </span>
          {c.subJa && <span className="tchg__sub">{c.subJa}</span>}
        </div>
      ))}
    </div>
  </section>
);
