import React from 'react';
import { ActionPill } from '../action/ActionBadge';
import type { CapitalRotationRow, FlowDirection, FlowStrength } from '../../types/regime';
import './CapitalRotationBoard.css';

interface Props {
  rows: CapitalRotationRow[];
}

const FLOW_ARROW: Record<FlowDirection, string> = {
  inflow:          '↑',
  'slight-inflow': '↗',
  neutral:         '→',
  'slight-outflow':'↘',
  outflow:         '↓',
};

const FLOW_LABEL: Record<FlowDirection, string> = {
  inflow:          'Inflow',
  'slight-inflow': 'Slight In',
  neutral:         'Neutral',
  'slight-outflow':'Slight Out',
  outflow:         'Outflow',
};

const STRENGTH_LABEL: Record<FlowStrength, string> = {
  low:  'L',
  med:  'M',
  high: 'H',
};

// Row-table of where money appears to be rotating across asset classes.
// Replaces the v5 "Capital Concentration" bubble — same intent (where
// money is), expressed as a serious financial diagnostic rather than a
// decorative visual.
export const CapitalRotationBoard: React.FC<Props> = ({ rows }) => {
  return (
    <div className="card rotation">
      {rows.map((r) => (
        <div className="rotation__row" key={r.assetClass}>
          <span className="rotation__asset">{r.assetClass}</span>
          <span className={`rotation__flow rotation__flow--${r.flow}`}>
            <span className="rotation__flow-arrow" aria-hidden>{FLOW_ARROW[r.flow]}</span>
            {FLOW_LABEL[r.flow]}
          </span>
          <span className={`rotation__strength rotation__strength--${r.strength}`}
            aria-label={`strength ${r.strength}`}>
            <span className="rotation__strength-bar" />
            <span className="rotation__strength-bar" />
            <span className="rotation__strength-bar" />
            <span style={{ marginLeft: 4 }}>{STRENGTH_LABEL[r.strength]}</span>
          </span>
          <span className="rotation__driver">{r.driver}</span>
          <span className="rotation__action">
            <ActionPill action={r.action} size="sm" />
          </span>
          <p className="rotation__next">
            <span className="rotation__next-label">Next</span>{r.nextCondition}
          </p>
        </div>
      ))}
    </div>
  );
};
