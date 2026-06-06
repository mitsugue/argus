import React from 'react';
import type { AssetActionCard } from '../../types/dashboard';
import { ActionPill } from '../action/ActionBadge';

interface Props {
  card: AssetActionCard;
}

const CONFIDENCE_LABEL = { low: 'Low', med: 'Med', high: 'High' } as const;
const RISK_LABEL = { low: 'Low', med: 'Med', high: 'High', extreme: 'Extreme' } as const;

export const AlertCard: React.FC<Props> = ({ card }) => {
  return (
    <article className="alert-card">
      <header className="alert-card__head">
        <span className="alert-card__class">{card.displayName}</span>
        <ActionPill action={card.action} size="sm" />
      </header>
      <p className="alert-card__reason">{card.reason}</p>
      <div className="alert-card__meta">
        <span className="alert-card__meta-item">
          Confidence
          <span className="alert-card__meta-value">{CONFIDENCE_LABEL[card.confidence]}</span>
        </span>
        <span className="alert-card__meta-item">
          Risk
          <span className="alert-card__meta-value">{RISK_LABEL[card.risk]}</span>
        </span>
      </div>
      <div className="alert-card__data">
        {card.dataPoints.map((d, i) => <span key={i}>{d}</span>)}
      </div>
      <p className="alert-card__next">
        <strong>Watch </strong>{card.nextCondition}
      </p>
    </article>
  );
};
