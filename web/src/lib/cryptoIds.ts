// v11.8.1 — CoinGecko id resolution with a symbol fallback map.
// ROOT CAUSE FIX (owner report 2026-07-04「XRP SOLの金額が出ない」): the add-asset
// flow only stores the `coingecko:<id>` memo when a search candidate is CLICKED.
// A manually-typed XRP/SOL had no memo, so every price-fetch site silently
// dropped the asset (id='') and it could never show a price. Now well-known
// symbols always resolve, memo or not. Mirrors backend _CG_TO_COINBASE.

import type { AssetItem } from '../types/assetItem';

export const SYMBOL_TO_COINGECKO: Record<string, string> = {
  BTC: 'bitcoin', ETH: 'ethereum', SOL: 'solana', XRP: 'ripple',
  ADA: 'cardano', DOGE: 'dogecoin', LTC: 'litecoin', DOT: 'polkadot',
  AVAX: 'avalanche-2', LINK: 'chainlink', MATIC: 'polygon-ecosystem-token', POL: 'polygon-ecosystem-token', TRX: 'tron',
  XLM: 'stellar', BCH: 'bitcoin-cash', UNI: 'uniswap', ATOM: 'cosmos',
  APT: 'aptos', ARB: 'arbitrum', OP: 'optimism', SHIB: 'shiba-inu', NEAR: 'near',
};

// 2026-11-15: CoinGecko stopped updating matic-network in February 2026; the
// token migrated 1:1 to POL, whose id is polygon-ecosystem-token.
const RETIRED_COINGECKO_IDS: Record<string, string> = { 'matic-network': 'polygon-ecosystem-token' };

/** memo (`coingecko:<id>`) → fallback map → ''. Never throws. */
export function coingeckoIdOf(a: Pick<AssetItem, 'symbol' | 'memo'>): string {
  const m = (a.memo ?? '').match(/coingecko:(\S+)/)?.[1];
  if (m) return RETIRED_COINGECKO_IDS[m] ?? m;
  return SYMBOL_TO_COINGECKO[a.symbol.toUpperCase()] ?? '';
}
