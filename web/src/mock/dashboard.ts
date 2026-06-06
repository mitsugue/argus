import type {
  AssetActionCard,
  CorePosition,
  DailyJudgment,
  MarketEvent,
} from '../types/dashboard';

// Static seed data — replaced by a real scanner backend later. Values
// chosen to reflect a plausible "event-risk Tuesday before CPI": cautious
// across satellites, steady on core. NOT trading advice.

export const todayJudgment: DailyJudgment = {
  date: '2026-06-09',
  overall: 'WAIT',
  risk: 'high',
  regime: ['Event Risk', 'Rates Pressure'],
  summary:
    'Conditions are unstable ahead of US CPI within 24 hours. Avoid aggressive entries; wait for confirmation after the release.',
  reasons: [
    'US CPI is scheduled within 24 hours and consensus is uncertain.',
    'US 10Y yield is rising — bond market is repricing rate expectations.',
    'Nasdaq futures opened weak with thin overnight breadth.',
  ],
  assetsToTouch: ['Gold (hedge)', 'Cash reserves', 'JP large-cap defensive'],
  assetsToAvoid: ['US growth stocks', 'High-beta crypto', 'Long-duration bonds'],
  nextCondition:
    'CPI print at 08:30 ET — wait for confirmation, then re-evaluate within 30 minutes.',
  updatedAt: Date.now(),
};

export const actionAlerts: AssetActionCard[] = [
  {
    assetClass: 'JP_STOCK',
    displayName: 'Japan Individual Stocks',
    action: 'WAIT',
    confidence: 'med',
    risk: 'med',
    reason: 'TSE breadth flat; major themes on hold ahead of US CPI.',
    dataPoints: [
      'TOPIX adv/dec ratio: 1.02',
      'Foreign net flow: -¥48bn (5d)',
      'Margin long ratio: 3.4 (elevated)',
    ],
    nextCondition: 'US CPI clears → re-screen morning gappers.',
  },
  {
    assetClass: 'US_STOCK',
    displayName: 'US Individual Stocks',
    action: 'WAIT_FOR_PullBACK' as never, // placeholder for typing; replaced below
    confidence: 'high',
    risk: 'high',
    reason: 'Mag-7 stretched, breadth weak — wait for orderly pullback.',
    dataPoints: [
      'SPX RSI(14): 71',
      '% > 50DMA: 58%',
      'VIX: 17.4 (rising)',
    ],
    nextCondition: 'SPX -2% intraday or VIX > 22 → re-evaluate.',
  },
  {
    assetClass: 'GOLD',
    displayName: 'Gold',
    action: 'HOLD',
    confidence: 'high',
    risk: 'low',
    reason: 'Holding as the event hedge — momentum positive but extended.',
    dataPoints: [
      'XAU/USD: 2,348 (+0.4% 5d)',
      'Real yield: 1.8% (range-bound)',
      'GLD net inflow: +$220m (5d)',
    ],
    nextCondition: 'CPI surprise to upside → trim partial.',
  },
  {
    assetClass: 'REIT',
    displayName: 'REITs',
    action: 'WAIT',
    confidence: 'med',
    risk: 'med',
    reason: 'Rate-sensitive — sit out until duration risk clears.',
    dataPoints: ['VNQ -1.1% (5d)', 'US 10Y: 4.42%'],
    nextCondition: '10Y back below 4.30% → re-evaluate.',
  },
  {
    assetClass: 'BOND',
    displayName: 'Bonds',
    action: 'WAIT_FOR_PULLBACK',
    confidence: 'high',
    risk: 'med',
    reason: 'Yields rising — wait for the curve to stabilize before adding duration.',
    dataPoints: [
      'TLT -1.8% (5d)',
      'US 10Y: 4.42% (+12 bps 5d)',
      '2s10s: -32 bps',
    ],
    nextCondition: '10Y peaks and reverses → start phased buys.',
  },
  {
    assetClass: 'CRYPTO',
    displayName: 'Crypto',
    action: 'TRIM',
    confidence: 'med',
    risk: 'high',
    reason: 'BTC/ETH extended into event risk — secure partial profit.',
    dataPoints: [
      'BTC: $68,200 (+9% 7d)',
      'ETH: $3,820 (+11% 7d)',
      'Funding: 0.04% (elevated)',
    ],
    nextCondition: 'Funding > 0.06% or BTC > $71k → trim more.',
  },
  {
    assetClass: 'COMMODITY',
    displayName: 'Commodities',
    action: 'WAIT',
    confidence: 'low',
    risk: 'med',
    reason: 'Mixed signals across oil and base metals — no clear edge.',
    dataPoints: ['WTI: $76.2', 'Copper: $4.18'],
    nextCondition: 'OPEC headline or China PMI surprise.',
  },
  {
    assetClass: 'USDJPY',
    displayName: 'USD/JPY',
    action: 'WAIT',
    confidence: 'high',
    risk: 'med',
    reason: 'Range-bound around 157 — intervention risk caps upside.',
    dataPoints: [
      'USD/JPY: 157.2',
      'MoF rhetoric: elevated',
      'Vol-1M: 8.4%',
    ],
    nextCondition: '158.5 break or BOJ comment → reassess.',
  },
];

// Patch the typo from above so we don't carry the bogus literal in shipped data.
actionAlerts[1].action = 'WAIT_FOR_PULLBACK';

export const indexFundStatus: CorePosition[] = [
  {
    symbol: 'eMAXIS Slim S&P 500',
    name: 'eMAXIS Slim S&P 500',
    market: 'JP',
    action: 'CONTINUE',
    reason: 'Monthly accumulation on schedule; valuation expensive but trend intact.',
  },
  {
    symbol: 'eMAXIS Slim All-Country',
    name: 'eMAXIS Slim All-Country (オルカン)',
    market: 'JP',
    action: 'CONTINUE',
    reason: 'Continue NISA monthly contribution as planned.',
  },
  {
    symbol: 'VTI',
    name: 'Vanguard Total Stock Market ETF',
    market: 'US',
    action: 'WAIT_LUMP',
    reason: 'Hold extra lump-sum until post-CPI re-pricing.',
  },
  {
    symbol: 'Nikkei 225 Index',
    name: 'Nikkei 225 Index Fund',
    market: 'JP',
    action: 'GRADUAL_ADD',
    reason: 'TOPIX pullback offers a phased entry — add over 3 weeks.',
  },
];

const day = 86_400_000;
const t0 = Date.now();

export const upcomingEvents: MarketEvent[] = [
  {
    id: 'cpi-jun',
    kind: 'CPI',
    title: 'US CPI (May)',
    at: t0 + 1 * day,
    impact: 'high',
    note: 'Headline expected 3.4% YoY. Largest single risk this week.',
  },
  {
    id: 'fomc-jun',
    kind: 'FOMC',
    title: 'FOMC Decision',
    at: t0 + 2 * day,
    impact: 'extreme',
    note: 'Rate held expected; dot plot & SEP are the variable.',
  },
  {
    id: 'pce-jun',
    kind: 'PCE',
    title: 'US PCE (May)',
    at: t0 + 22 * day,
    impact: 'high',
  },
  {
    id: 'boj-jul',
    kind: 'BOJ',
    title: 'BOJ Policy Meeting',
    at: t0 + 30 * day,
    impact: 'high',
    note: 'JGB taper pace and FX guidance in focus.',
  },
  {
    id: 'nflx-q',
    kind: 'EARNINGS',
    title: 'NFLX Earnings',
    at: t0 + 12 * day,
    impact: 'med',
  },
];
