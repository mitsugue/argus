import React from 'react';
import type { TodayExposureView } from '../../domain/todayOverview';
import type { RouteKey } from '../NavRail';
import './Today.css';

// V12.2.11 — Your Exposure: 「その変化が自分の保有に何を意味するか」(≤3件)。
// 保有なしは静かな空状態+導線1つだけ(警告の羅列はしない)。

export const YourExposureCard: React.FC<{
  exposures: TodayExposureView[];
  noHoldings: boolean;
  onNavigate: (key: RouteKey) => void;
}> = ({ exposures, noHoldings, onNavigate }) => (
  <section className="tcard tg-span-5" aria-label="Your exposure">
    <div className="tcard__head">
      <span className="tcard__title">Your Exposure</span>
    </div>
    {noHoldings ? (
      <div className="texp__empty">
        <p className="texp__empty-title">No positions configured</p>
        保有情報を登録すると、市場変化が自分の資産に与える影響をここに表示します。
        <div>
          <button type="button" className="texp__cta" onClick={() => onNavigate('core')}>
            Positions &amp; Risk で保有を登録
          </button>
        </div>
      </div>
    ) : exposures.length === 0 ? (
      <p className="texp__empty">保有資産への明確な警報はありません。</p>
    ) : (
      <div className="texp">
        {exposures.map((e) => (
          <div className="texp__row" key={e.id}>
            <div className="texp__top">
              <span className="texp__name">{e.titleJa}</span>
              <span className={`texp__impact texp__impact--${e.severityEn.toLowerCase()}`}>
                {e.impactEn} / {e.severityEn}
              </span>
            </div>
            <p className="texp__why">{e.whyJa}</p>
          </div>
        ))}
      </div>
    )}
  </section>
);
