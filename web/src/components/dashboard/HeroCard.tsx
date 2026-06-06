import React from 'react';
import type { DailyJudgment } from '../../types/dashboard';
import { ActionHero } from '../action/ActionBadge';
import { RiskIndicator } from './RiskIndicator';

interface Props {
  judgment: DailyJudgment;
}

// The single most important card: today's overall judgment. Designed to
// answer the user's 10-second question — what is the call and why.
export const HeroCard: React.FC<Props> = ({ judgment }) => {
  return (
    <article className="card card--hero hero">
      <div className="hero__row">
        <div className="hero__primary">
          <span className="hero__label">Overall Judgment</span>
          <div className="hero__judgment">
            <ActionHero action={judgment.overall} />
          </div>
        </div>
        <div className="hero__attrs">
          <div className="hero__attr">
            <span className="hero__label">Risk Level</span>
            <span className="hero__attr-value">
              <RiskIndicator level={judgment.risk} />
            </span>
          </div>
          <div className="hero__attr">
            <span className="hero__label">Market Regime</span>
            <div className="hero__regime-tags">
              {judgment.regime.map((r) => (
                <span className="hero__tag" key={r}>{r}</span>
              ))}
            </div>
          </div>
        </div>
      </div>

      <p className="hero__summary">{judgment.summary}</p>

      <div className="hero__reasons">
        <span className="hero__reasons-label">Top reasons</span>
        {judgment.reasons.map((r, i) => (
          <div className="hero__reason" key={i}>
            <span className="hero__reason-num">{String(i + 1).padStart(2, '0')}</span>
            <span>{r}</span>
          </div>
        ))}
      </div>

      <div className="hero__lists">
        <div className="hero__list-block">
          <span className="hero__list-label">Touch today</span>
          <div className="hero__list-items">
            {judgment.assetsToTouch.map((a) => <span key={a}>{a}</span>)}
          </div>
        </div>
        <div className="hero__list-block">
          <span className="hero__list-label">Avoid today</span>
          <div className="hero__list-items hero__list-items--avoid">
            {judgment.assetsToAvoid.map((a) => <span key={a}>{a}</span>)}
          </div>
        </div>
      </div>

      <div className="hero__next">
        <span className="hero__next-label">Next condition</span>
        <span className="hero__next-text">{judgment.nextCondition}</span>
      </div>
    </article>
  );
};
