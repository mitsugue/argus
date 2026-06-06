import React from 'react';
import type { CorePosition } from '../../types/dashboard';
import { ActionPill } from '../action/ActionBadge';

interface Props {
  position: CorePosition;
}

export const CoreRow: React.FC<Props> = ({ position }) => {
  return (
    <div className="core-row">
      <div className="core-row__body">
        <div className="core-row__top">
          <span>{position.name}</span>
          <span className="core-row__market">· {position.market}</span>
        </div>
        <span className="core-row__reason">{position.reason}</span>
      </div>
      <ActionPill action={position.action} />
    </div>
  );
};
