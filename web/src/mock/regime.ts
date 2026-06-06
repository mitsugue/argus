import type {
  CapitalRotationRow,
  RegimeMatrixState,
  TopRotation,
} from '../types/regime';

// "Tuesday before US CPI" mock state. Posture is WAIT; the upper-left
// quadrant (Risk Off + Rates Pressure) is active. NOT a forecast.

export const regimeMatrix: RegimeMatrixState = {
  x: -0.55,
  y: 0.65,
  quadrantLabel: 'Risk Off / Rates Pressure',
  primaryRegime: 'Event Risk',
  secondaryRegime: 'Rates Pressure',
  posture: 'CPI 通過まで新規エントリーを抑制。デュレーション資産は様子見。',
  assets: [
    { label: 'US Growth', x: 0.25, y: 0.70 },
    { label: 'JP Stocks', x: 0.05, y: 0.30 },
    { label: 'Gold',      x: -0.45, y: 0.15 },
    { label: 'Bonds',     x: -0.30, y: 0.50 },
    { label: 'Crypto',    x: 0.55, y: 0.40 },
    { label: 'REITs',     x: -0.20, y: 0.55 },
    { label: 'Cash',      x: -0.75, y: -0.20 },
  ],
};

export const rotationBoard: CapitalRotationRow[] = [
  {
    assetClass: 'US Equities',
    flow: 'slight-outflow',
    strength: 'med',
    driver: 'Event Risk',
    action: 'WAIT',
    nextCondition: 'CPI 通過後にブレッドスを再評価。',
  },
  {
    assetClass: 'Japan Equities',
    flow: 'neutral',
    strength: 'med',
    driver: 'Event Risk',
    action: 'WAIT',
    nextCondition: '米市場の方向感が見えるまで様子見。',
  },
  {
    assetClass: 'US Growth / High Beta',
    flow: 'outflow',
    strength: 'high',
    driver: 'Rates Pressure',
    action: 'WAIT_FOR_PULLBACK',
    nextCondition: '10Y がピークアウトすれば段階エントリー。',
  },
  {
    assetClass: 'Japan Individual Stocks',
    flow: 'neutral',
    strength: 'med',
    driver: 'Event Risk',
    action: 'WAIT',
    nextCondition: 'US CPI の方向感を見て翌朝再スクリーン。',
  },
  {
    assetClass: 'Bonds',
    flow: 'neutral',
    strength: 'low',
    driver: 'Yield Watch',
    action: 'WAIT_FOR_PULLBACK',
    nextCondition: '10Y のピーク確認 → デュレーション拡大。',
  },
  {
    assetClass: 'Gold',
    flow: 'inflow',
    strength: 'med',
    driver: 'Hedge Demand',
    action: 'HOLD',
    nextCondition: 'CPI 上振れ → 部分利確。',
  },
  {
    assetClass: 'REITs',
    flow: 'outflow',
    strength: 'med',
    driver: 'Rates Pressure',
    action: 'WAIT',
    nextCondition: '10Y が 4.30% を割れば再評価。',
  },
  {
    assetClass: 'Crypto',
    flow: 'outflow',
    strength: 'high',
    driver: 'Crypto Heat Cooling',
    action: 'TRIM',
    nextCondition: 'ファンディング > 0.06% → さらに利確。',
  },
  {
    assetClass: 'USD/JPY',
    flow: 'neutral',
    strength: 'med',
    driver: 'JPY Shock 警戒',
    action: 'WAIT',
    nextCondition: '158.5 突破または BOJ コメント → 再評価。',
  },
  {
    assetClass: 'Cash',
    flow: 'inflow',
    strength: 'med',
    driver: 'Defensive Rotation',
    action: 'HOLD',
    nextCondition: 'CPI 通過後の押し目を待つ。',
  },
];

// Today's 3-second money-flow scan. Lighter than the full board.
export const topRotations: TopRotation[] = [
  { from: 'Growth',       to: 'Cash' },
  { from: 'High Beta',    to: 'Gold' },
  { from: 'New Entries',  to: 'Deferred' },
  { from: 'REITs',        to: 'Wait until rates cool' },
  { from: 'Crypto',       to: 'Trim overheated names' },
];
