import React from 'react';
import type { TodayNextCheckView } from '../../domain/todayOverview';
import './Today.css';

// V12.2.11 — Next Check: 「次にいつ・何を見るか」を必ず1件だけ。
// 曖昧な「あとで/市場次第」は出さない(builderが正確な時刻源から選ぶ)。

export const NextCheckCard: React.FC<{ nextCheck: TodayNextCheckView }> = ({ nextCheck }) => (
  <section className="tcard tg-span-4" aria-label="Next check">
    <div className="tcard__head">
      <span className="tcard__title">Next Check</span>
    </div>
    <div className="tnext__when">{nextCheck.whenJa}</div>
    <p className="tnext__what">{nextCheck.whatJa}</p>
  </section>
);
