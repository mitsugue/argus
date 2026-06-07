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

// Capital Rotation Board — three signals only: Flow, Strength, Role.
// No action labels here; those live on Action Alerts / Watchlist.
export const rotationBoard: CapitalRotationRow[] = [
  { assetClass: 'US Equities',            flow: 'Slight Outflow', flowValue: -25, strength: 'Medium', role: 'Risk' },
  { assetClass: 'Japan Equities',         flow: 'Neutral',         flowValue:   0, strength: 'Medium', role: 'Risk' },
  { assetClass: 'US Growth / High Beta',  flow: 'Outflow',         flowValue: -70, strength: 'High',   role: 'Risk' },
  { assetClass: 'Gold',                   flow: 'Inflow',          flowValue:  65, strength: 'Medium', role: 'Hedge' },
  { assetClass: 'Cash',                   flow: 'Inflow',          flowValue:  55, strength: 'Medium', role: 'Liquidity' },
  { assetClass: 'Crypto',                 flow: 'Outflow',         flowValue: -75, strength: 'High',   role: 'Risk' },
  { assetClass: 'Bonds',                  flow: 'Neutral',         flowValue:   5, strength: 'Low',    role: 'Duration' },
  { assetClass: 'REITs',                  flow: 'Slight Outflow',  flowValue: -35, strength: 'Medium', role: 'Duration' },
  { assetClass: 'USD/JPY',                flow: 'Neutral',         flowValue:  10, strength: 'Medium', role: 'Liquidity' },
];

// Today's 3-second money-flow scan — same conceptual signal as the full
// board, compressed to one-line "from → to" headlines.
export const topRotations: TopRotation[] = [
  { from: 'Growth',      to: 'Cash' },
  { from: 'High Beta',   to: 'Gold' },
  { from: 'New Entries', to: 'Deferred' },
  { from: 'REITs',       to: 'Wait until rates cool' },
  { from: 'Crypto',      to: 'Outflow' },
  { from: 'Bonds',       to: 'Neutral / Watch' },
];

// Short prose summary rendered below the matrix on the regime page.
// English header line + JP body, matching the bilingual chrome/content
// split used elsewhere.
export const regimeSummary = {
  headline: 'Current location: Risk Off / Rates Pressure.',
  body: 'ハイベータ・グロース株から資金が流出し、現金・金・ディフェンシブへ回転している。CPI 通過まで新規の積極エントリーは抑制し、デュレーション資産は様子見が妥当。',
};
