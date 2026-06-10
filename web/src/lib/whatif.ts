// What-if simulator (v10.1) — "if I add ¥X to asset Y, what changes?"
// SCENARIO ANALYSIS, NOT PREDICTION: outcomes are coarse assumed bands per
// scenario, weighted by the rule engine's scenario probabilities. Everything
// runs client-side on device-local holdings. ARGUS classifies; it never
// promises a future price.

import type { ScenarioProb } from './assetStrategy';
import type { ExposureSummary } from './portfolio';
import type { Ccy } from './portfolio';

// Assumed 1–3 trading-day move bands per scenario (% of position). Coarse and
// transparent BY DESIGN — shown to the user as 仮定幅, never as a forecast.
export const SCENARIO_BANDS: Record<string, [number, number]> = {
  downside_continuation: [-10, -4],
  sideways_stabilization: [-2, 2],
  rebound_attempt: [3, 8],
};

export interface WhatIfBand {
  label: string;
  labelJa: string;
  probability: number;     // %
  bandPct: [number, number];
  plLow: number;           // native currency, on the ADDED amount
  plHigh: number;
}

export interface WhatIfResult {
  currency: Ccy;
  amount: number;            // added investment (native ccy)
  addQuantity: number;       // amount / price
  price: number;
  bands: WhatIfBand[];
  /** Probability-weighted midpoint P/L of the added amount (native ccy). */
  expectedMid: number;
  /** Portfolio shares (JPY-combined). Null when conversion is unavailable. */
  assetShareBeforePct: number | null;
  assetShareAfterPct: number | null;
  portfolioAfterJpy: number | null;
  warnings: string[];
}

export function simulateAdd(args: {
  symbol: string;
  currency: Ccy;
  price: number;
  amount: number;                    // native currency
  scenarios: ScenarioProb[];
  exposure: ExposureSummary;
  usdJpy: number | null;
}): WhatIfResult | null {
  const { symbol, currency, price, amount, scenarios, exposure, usdJpy } = args;
  if (!(amount > 0) || !(price > 0)) return null;

  const bands: WhatIfBand[] = scenarios
    .filter((s) => SCENARIO_BANDS[s.label])
    .map((s) => {
      const [lo, hi] = SCENARIO_BANDS[s.label];
      return {
        label: s.label, labelJa: s.labelJa, probability: s.probability,
        bandPct: [lo, hi] as [number, number],
        plLow: amount * (lo / 100), plHigh: amount * (hi / 100),
      };
    });
  const expectedMid = bands.reduce(
    (acc, b) => acc + (b.probability / 100) * ((b.plLow + b.plHigh) / 2), 0);

  const toJpy = (ccy: Ccy, v: number): number | null =>
    ccy === 'JPY' ? v : usdJpy != null ? v * usdJpy : null;
  const amountJpy = toJpy(currency, amount);
  const beforeJpy = exposure.combinedJpy;
  const assetNowJpy = (() => {
    const h = exposure.holdings.find((x) => x.symbol === symbol);
    if (!h) return 0;
    return toJpy(h.currency, h.value) ?? null;
  })();

  let assetShareBeforePct: number | null = null;
  let assetShareAfterPct: number | null = null;
  let portfolioAfterJpy: number | null = null;
  if (beforeJpy != null && amountJpy != null && assetNowJpy != null) {
    portfolioAfterJpy = beforeJpy + amountJpy;
    assetShareBeforePct = beforeJpy > 0 ? (assetNowJpy / beforeJpy) * 100 : null;
    assetShareAfterPct = portfolioAfterJpy > 0 ? ((assetNowJpy + amountJpy) / portfolioAfterJpy) * 100 : null;
  }

  const warnings: string[] = [];
  if (assetShareAfterPct != null && assetShareAfterPct > 30) {
    warnings.push(`この追加で ${symbol} がポートフォリオの${assetShareAfterPct.toFixed(0)}%になり、集中リスクが高まります(目安30%超)。`);
  }
  return {
    currency, amount, addQuantity: amount / price, price,
    bands, expectedMid,
    assetShareBeforePct, assetShareAfterPct, portfolioAfterJpy,
    warnings,
  };
}
