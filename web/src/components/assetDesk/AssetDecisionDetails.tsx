import React from 'react';
import type { DeskCardData } from './types';
import { SIGNALS } from '../../domain/actionLevel';
import { valueHolding, fmtMoney } from '../../lib/portfolio';
import { deskSignalCode } from './AssetDecisionSummary';

/** First viewport only: one command, one reason, one next check and one change condition. */
export const AssetDecisionDetails: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const view = d.decisionFirst;
  const code = deskSignalCode(d);
  const signal = SIGNALS[code];
  const livePrice = d.strat.status === 'live' || d.strat.status === 'partial'
    ? d.strat.price : undefined;
  const holding = valueHolding(d.asset, livePrice);
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

      <div className="ad-overview__position">
        <span>OWNER POSITION</span>
        {view.held ? (
          <div className="ad-position-stats">
            <b>{d.asset.quantity?.toLocaleString() ?? '数量未入力'} 株/口</b>
            <small>取得 {d.asset.avgCost?.toLocaleString() ?? '未入力'}</small>
            <small>評価 {holding ? fmtMoney(holding.currency, holding.value) : '未計算'}</small>
            <small className={view.pnlPct != null && view.pnlPct < 0 ? 'is-negative' : 'is-positive'}>
              損益 {view.pnlPct == null ? '未計算'
                : `${view.pnlPct >= 0 ? '+' : ''}${view.pnlPct.toFixed(1)}%`}
            </small>
            {d.pn?.weightPct != null && <small>集中 {d.pn.weightPct.toFixed(0)}%</small>}
          </div>
        ) : <b>監視のみ（保有なし）</b>}
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
