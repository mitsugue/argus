import React from 'react';
import { ActionPill } from '../action/ActionBadge';
import type { CorePosition } from '../../types/dashboard';

interface Props {
  position: CorePosition;
  // A short alias for the home preview ("JP Core", "US ETF" etc.) — falls
  // back to position.name when not provided.
  shortLabel?: string;
}

// Today-page core row — just the label + action pill. No reason quote.
// The full per-position reasoning lives on the Core Portfolio page.
export const CompactCoreRow: React.FC<Props> = ({ position, shortLabel }) => {
  return (
    <div className="core-row">
      <div className="core-row__body">
        <div className="core-row__top">
          <span>{shortLabel ?? position.name}</span>
        </div>
      </div>
      <ActionPill action={position.action} />
    </div>
  );
};
