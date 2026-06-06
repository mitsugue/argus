import React from 'react';
import type { TopRotation } from '../../types/regime';
import './TopRotations.css';

interface Props {
  rotations: TopRotation[];
}

// 3-second money-flow summary for the Today page. The full Capital
// Rotation Board lives on the Market Regime detail page; here we just
// want the headline movements.
export const TopRotations: React.FC<Props> = ({ rotations }) => {
  return (
    <div className="card top-rotations">
      {rotations.map((r) => (
        <div className="top-rotations__row" key={`${r.from}->${r.to}`}>
          <span className="top-rotations__from">{r.from}</span>
          <span className="top-rotations__arrow" aria-hidden>→</span>
          <span className="top-rotations__to">{r.to}</span>
        </div>
      ))}
    </div>
  );
};
