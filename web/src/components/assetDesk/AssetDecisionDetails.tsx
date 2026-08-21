import React from 'react';
import type { DeskCardData } from './types';

const ACTION_TONE = { BUY: 'var(--value-positive)', HOLD: 'var(--accent)',
  WAIT: 'var(--amber, #fbbf24)', REDUCE: 'var(--event-high)', EXIT: 'var(--value-negative)' };

/** First viewport only: one command, one reason, one next check and one change condition. */
export const AssetDecisionDetails: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const view = d.decisionFirst;
  const tone = ACTION_TONE[view.canonicalPrimaryAction ?? 'WAIT'];
  return (
    <div className="ad-overview" data-decision-overview={view.symbol}>
      <div className="ad-overview__action">
        <span>いまの判断</span>
        <strong style={{ color: tone }}>{view.currentActionJa}</strong>
        <div>
          <small>保有中</small><b>{view.ownerActionJa}</b>
          <small>新規</small><b>{view.entryActionJa}</b>
        </div>
      </div>

      <dl className="ad-overview__facts">
        <div><dt>理由</dt><dd>{view.whyJa}</dd></div>
        <div><dt>次に確認すること</dt><dd>{view.nextJa}</dd></div>
        <div><dt>判断が変わる条件</dt><dd>{view.whatChangesJa}</dd></div>
        {view.targets[0] && <div><dt>目標</dt><dd>{`${view.targets[0].value} ${view.targets[0].unit}`}</dd></div>}
        {view.invalidation && <div><dt>無効化条件</dt><dd>{`${view.invalidation.value} ${view.invalidation.unit}`}</dd></div>}
      </dl>

      {view.dataStatus !== 'LIVE' && view.dataStatus !== 'live' && (
        <p className="ad-overview__warning">データ状態：{view.dataStatus}。未取得値を判断根拠として補完しません。</p>
      )}
    </div>
  );
};
