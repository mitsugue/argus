import type { ChartIntelligencePayload, MarketReplayContext } from '../types/chartIntelligence';

export interface MarketContextView {
  regime: string;
  changed: string;
  primaryRisk: string;
  jpImplication: string;
  usImplication: string;
  nextEvent: string;
  changeCondition: string;
}

const fmtPct = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;

export function buildMarketContextView(
  data: ChartIntelligencePayload,
  replay: MarketReplayContext | null,
): MarketContextView {
  const bars = data.indicators.bars;
  const previous = bars.at(-2)?.close;
  const current = bars.at(-1)?.close;
  const dailyChange = previous != null && previous !== 0 && current != null
    ? ((current / previous) - 1) * 100 : null;
  const trend = replay?.currentRegime.trend ?? '未分類';
  const volatility = replay?.currentRegime.volatility ?? '未分類';
  const selectedMarket = data.market === 'JP' ? 'JP' : 'US';
  const futureEvent = [...data.eventMarkers]
    .filter((event) => !data.periodEnd || event.date >= data.periodEnd)
    .sort((a, b) => a.date.localeCompare(b.date))[0];
  const condition = replay?.changeConditions[0];
  const selectedImplication = `trend ${trend} / volatility ${volatility}を個別判断へ反映`;
  const independentImplication = '独立市場のinstrumentへ切替えて確認';

  return {
    regime: `${trend} · ${volatility}`,
    changed: dailyChange == null
      ? '比較可能な前回終値なし'
      : `直近終値 ${fmtPct(dailyChange)} · trend ${trend}`,
    primaryRisk: volatility === '未分類'
      ? 'volatility判定待ち'
      : `volatility ${volatility} · ${replay?.probabilityQuality.brierSkill != null
        && replay.probabilityQuality.brierSkill > 0 ? '予測Skillあり' : '方向Skill未確認'}`,
    jpImplication: selectedMarket === 'JP' ? selectedImplication : independentImplication,
    usImplication: selectedMarket === 'US' ? selectedImplication : independentImplication,
    nextEvent: futureEvent ? `${futureEvent.date} · ${futureEvent.labelJa}` : '登録済みの次イベントなし',
    changeCondition: !condition
      ? '自然tickの検証済み条件を待機'
      : condition.price == null
        ? (condition.event ?? '次の確認条件を待機')
        : `${condition.price.toLocaleString('ja-JP')} 終値確認`,
  };
}
