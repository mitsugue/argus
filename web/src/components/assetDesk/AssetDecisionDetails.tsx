import React from 'react';
import type { DeskCardData } from './types';
import { SIGNALS } from '../../domain/actionLevel';
import { deskSignalCode } from './AssetDecisionSummary';

/** First viewport only: one command, one reason, one next check and one change condition. */
export const AssetDecisionDetails: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const view = d.decisionFirst;
  const code = deskSignalCode(d);
  const signal = SIGNALS[code];
  return (
    <div className="ad-overview" data-decision-overview={view.symbol}>
      <div className="ad-overview__action">
        <span>CURRENT ACTION</span>
        <strong style={{ color: `var(${signal.token})` }}>{view.currentActionJa}</strong>
        <div>
          <small>保有</small><b>{view.ownerActionJa}</b>
          <small>新規</small><b>{view.entryActionJa}</b>
        </div>
      </div>

      <dl className="ad-overview__facts">
        <div><dt>WHY NOW</dt><dd>{view.whyJa}</dd></div>
        <div><dt>NEXT CHECK</dt><dd>{view.nextJa}</dd></div>
        <div><dt>WHAT CHANGES IT</dt><dd>{view.whatChangesJa}</dd></div>
      </dl>

      {view.dataStatus !== 'LIVE' && view.dataStatus !== 'live' && (
        <p className="ad-overview__warning">データ状態：{view.dataStatus}。未取得値を判断根拠として補完しません。</p>
      )}
    </div>
  );
};
