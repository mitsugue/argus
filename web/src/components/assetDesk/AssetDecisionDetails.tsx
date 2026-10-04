import React from 'react';
import type { DeskCardData } from './types';
import { useAnalystTargets, type AnalystTarget } from '../../hooks/useAnalystTargets';

const ACTION_TONE = { BUY: 'var(--value-positive)', HOLD: 'var(--accent)',
  WAIT: 'var(--amber, #fbbf24)', REDUCE: 'var(--event-high)', EXIT: 'var(--value-negative)' };

const money = (v: number, currency: string | null) => currency === 'USD'
  ? `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}` : `${Math.round(v).toLocaleString('ja-JP')}円`;
const fetchedDay = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' });
};

/** Consensus of analysts' target prices: the mean and the spread, with a small source note (2026-10-04). */
function TargetRow({ target }: { target: AnalystTarget }) {
  const c = target.currency;
  return <div data-analyst-target={target.symbol}><dt>アナリスト目標株価</dt><dd>
    平均 {money(target.mean, c)}{target.gapPct != null && `（${target.gapPct > 0 ? '+' : ''}${target.gapPct.toFixed(1)}%）`}
    {target.low != null && target.high != null && ` ・ 予想の幅 ${money(target.low, c)}〜${money(target.high, c)}`}
    <small className="ad-overview__source">{target.source} · {fetchedDay(target.fetchedAt)}取得 · {target.analysts}人</small>
  </dd></div>;
}

/** First viewport only: one command, one reason, one next check and one change condition. */
export const AssetDecisionDetails: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const view = d.decisionFirst;
  const tone = ACTION_TONE[view.canonicalPrimaryAction ?? 'WAIT'];
  const targets = useAnalystTargets();
  const market = d.genre === 'jp' ? 'JP' : d.genre === 'us' ? 'US' : null;
  const target = market ? targets[`${market}:${String(view.symbol).toUpperCase()}`] : undefined;
  return (
    <div className="ad-overview" data-decision-overview={view.symbol}>
      <div className="ad-overview__action">
        <span>いまの判断</span>
        <strong style={{ color: tone }}>{view.currentActionJa}</strong>
      </div>

      <dl className="ad-overview__facts">
        <div><dt>理由</dt><dd>{view.whyJa}</dd></div>
        <div><dt>次に確認すること</dt><dd>{view.nextJa}</dd></div>
        <div><dt>判断が変わる条件</dt><dd>{view.whatChangesJa}</dd></div>
        {target && <TargetRow target={target} />}
        {view.targets[0] && <div><dt>目標</dt><dd>{`${view.targets[0].value} ${view.targets[0].unit}`}</dd></div>}
        {view.invalidation && <div><dt>無効化条件</dt><dd>{`${view.invalidation.value} ${view.invalidation.unit}`}</dd></div>}
      </dl>

      {view.dataStatus !== 'LIVE' && view.dataStatus !== 'live' && (
        <p className="ad-overview__warning">データ状態：{view.dataStatus}。未取得値を判断根拠として補完しません。</p>
      )}
    </div>
  );
};
