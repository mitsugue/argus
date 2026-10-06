import React from 'react';
import type { SupplyDemandSignal } from '../../hooks/useSupplyDemand';
import { SUPPLY_RANK_TONE as RANK_TONE } from '../../domain/assetOutlook';
import { analystTargetGap, outlookDay, outlookMoney, type AnalystTarget } from '../../domain/assetOutlook';

/** Facts visible before opening a card. No decisions or forecasts generated here. */
export const AssetOutlookSummary: React.FC<{
  market: string; target?: AnalystTarget; targetStatus?: string; loading: boolean;
  refreshFailed: boolean; currentPrice: number | null; supply?: SupplyDemandSignal;
}> = ({ market, target, targetStatus, loading, refreshFailed, currentPrice, supply }) => {
  if (market !== 'JP' && market !== 'US') return null;
  if (supply?.market !== market) supply = undefined;
  const staleSupply = supply?.directness === 'stale_context';
  const gap = target ? analystTargetGap(target, currentPrice) : null;
  const saved = !!target && (refreshFailed || (target.acquisitionStatus && target.acquisitionStatus !== 'AVAILABLE'));
  const dates = supply?.sourceDates;
  const supplyDates = [dates?.weeklyMargin ? `信用 ${outlookDay(dates.weeklyMargin)}` : null,
    dates?.jsfDaily ? `日証金 ${outlookDay(dates.jsfDaily)}` : null].filter(Boolean).join(' · ');
  const availableRank = supply && supply.supplyDemandRank !== 'Unknown';
  return <span className="ad-outlook" data-asset-outlook={market}>
    <span className="ad-outlook__line" data-target-summary="true">
      <span>アナリスト目標</span>
      {target ? <><strong>{outlookMoney(target.mean, market)}</strong>
        {gap != null && <span>現在値比 {gap >= 0 ? '+' : ''}{gap.toFixed(1)}%</span>}</>
        : <span>{loading ? '確認中' : refreshFailed || (targetStatus && targetStatus !== 'NO_TARGET')
          ? '取得未確認' : targetStatus === 'NO_TARGET' ? '取得元に目標値なし' : '未取得'}</span>}
    </span>
    {target && <span className="ad-outlook__source">平均 · {target.analysts}人 · {target.source} · {outlookDay(target.fetchedAt)}取得{saved ? ' · 更新未確認・保存値' : ''}</span>}
    <span className="ad-outlook__line" data-supply-summary="true">
      <span>需給</span><strong style={{ color: RANK_TONE[supply?.supplyDemandRank ?? 'Unknown'] }}>
        {availableRank && supply ? `${staleSupply ? '保存評価 ' : ''}${supply.supplyDemandRank} · ${supply.conditionJa}` : '判定保留'}</strong>
      {availableRank && supply && supply.supplyDemandLevel && supply.supplyDemandLevel !== 'unknown'
        && <span>買い残 {supply.levelJa}</span>}
    </span>
    <span className="ad-outlook__source">{market === 'US' ? '実測大口フローによる簡易評価' : supplyDates || '信用残・日証金の取得時点を確認中'}
      {staleSupply ? ' · 更新未確認・再確認用' : !supply || supply.directness !== 'direct_data' ? ' · データ不足'
        : market === 'JP' && (!dates?.weeklyMargin || !dates?.jsfDaily) ? ' · 一部未取得' : ''}</span>
  </span>;
};
