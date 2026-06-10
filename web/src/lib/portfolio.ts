// Portfolio Exposure (v10.0) — pure valuation math over the user's holdings.
// Privacy by design: quantity/avgCost live ONLY in localStorage and every
// computation here runs in the browser. Nothing is uploaded.
// This is CURRENT valuation + unrealized P/L — classification, not prediction.

import type { AssetItem } from '../types/assetItem';
import { genreOf, GENRES, type GenreKey } from '../types/assetItem';

export type Ccy = 'JPY' | 'USD';

export function currencyOf(market: AssetItem['market']): Ccy {
  return market === 'JP' ? 'JPY' : 'USD'; // US equities + crypto are USD-quoted
}

export interface HoldingValuation {
  symbol: string;
  name: string;
  genre: GenreKey;
  currency: Ccy;
  quantity: number;
  avgCost: number;
  price: number;
  value: number;     // quantity × price
  cost: number;      // quantity × avgCost
  pl: number;        // value − cost
  plPct: number;     // pl / cost × 100
}

export interface ExposureSummary {
  holdings: HoldingValuation[];
  totals: Record<Ccy, { value: number; cost: number; pl: number }>;
  /** Combined total in JPY (USD legs converted at usdJpy); null without a rate. */
  combinedJpy: number | null;
  combinedPlJpy: number | null;
  /** Allocation by genre in % of the JPY-combined total (empty without a rate
      unless everything is single-currency). */
  byGenre: { key: GenreKey; title: string; pct: number; valueJpy: number }[];
  usdJpy: number | null;
  /** Assets with a quantity but no usable live price (excluded, listed honestly). */
  unpriced: string[];
}

export function valueHolding(asset: AssetItem, price: number | undefined): HoldingValuation | null {
  const q = asset.quantity, c = asset.avgCost;
  if (q == null || c == null || q <= 0 || price == null || !Number.isFinite(price)) return null;
  const value = q * price;
  const cost = q * c;
  return {
    symbol: asset.symbol,
    name: asset.displayNameJa || asset.displayName,
    genre: genreOf(asset),
    currency: currencyOf(asset.market),
    quantity: q, avgCost: c, price,
    value, cost, pl: value - cost,
    plPct: cost > 0 ? ((value - cost) / cost) * 100 : 0,
  };
}

export function buildExposure(
  assets: AssetItem[],
  priceOf: (a: AssetItem) => number | undefined,
  usdJpy: number | null,
): ExposureSummary {
  const holdings: HoldingValuation[] = [];
  const unpriced: string[] = [];
  for (const a of assets) {
    if (a.quantity == null || a.quantity <= 0 || a.avgCost == null) continue;
    const v = valueHolding(a, priceOf(a));
    if (v) holdings.push(v);
    else unpriced.push(a.symbol);
  }
  const totals: ExposureSummary['totals'] = {
    JPY: { value: 0, cost: 0, pl: 0 },
    USD: { value: 0, cost: 0, pl: 0 },
  };
  for (const h of holdings) {
    totals[h.currency].value += h.value;
    totals[h.currency].cost += h.cost;
    totals[h.currency].pl += h.pl;
  }
  const toJpy = (ccy: Ccy, v: number): number | null =>
    ccy === 'JPY' ? v : usdJpy != null ? v * usdJpy : null;

  let combinedJpy: number | null = 0;
  let combinedPlJpy: number | null = 0;
  for (const ccy of ['JPY', 'USD'] as Ccy[]) {
    if (totals[ccy].value === 0) continue;
    const v = toJpy(ccy, totals[ccy].value);
    const p = toJpy(ccy, totals[ccy].pl);
    if (v == null || p == null) { combinedJpy = null; combinedPlJpy = null; break; }
    combinedJpy! += v;
    combinedPlJpy! += p;
  }
  if (holdings.length === 0) { combinedJpy = null; combinedPlJpy = null; }

  const byGenre: ExposureSummary['byGenre'] = [];
  if (combinedJpy != null && combinedJpy > 0) {
    for (const g of GENRES) {
      let v = 0;
      let ok = true;
      for (const h of holdings.filter((x) => x.genre === g.key)) {
        const j = toJpy(h.currency, h.value);
        if (j == null) { ok = false; break; }
        v += j;
      }
      if (ok && v > 0) byGenre.push({ key: g.key, title: g.title, pct: (v / combinedJpy) * 100, valueJpy: v });
    }
  }
  return { holdings, totals, combinedJpy, combinedPlJpy, byGenre, usdJpy, unpriced };
}

export function fmtMoney(ccy: Ccy, v: number): string {
  if (ccy === 'JPY') return `¥${Math.round(v).toLocaleString('en-US')}`;
  return `$${v.toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: v < 100 ? 2 : 0 })}`;
}

export function fmtSigned(ccy: Ccy, v: number): string {
  const s = v > 0 ? '+' : v < 0 ? '−' : '±';
  return `${s}${fmtMoney(ccy, Math.abs(v))}`;
}
