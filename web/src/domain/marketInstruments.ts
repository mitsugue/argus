export type MarketInstrumentSymbol = '1321' | '1306' | 'SPY' | 'QQQ';
export type MarketInstrumentMarket = 'JP' | 'US';
export type MarketHorizon = 1 | 5 | 20;

export interface MarketInstrumentDefinition {
  symbol: MarketInstrumentSymbol;
  market: MarketInstrumentMarket;
  shortLabel: string;
  fullLabel: string;
  verifiedDaily: true;
}

export const MARKET_INSTRUMENTS: readonly MarketInstrumentDefinition[] = [
  { symbol: '1321', market: 'JP', shortLabel: '日経',
    fullLabel: '日経225 ETF（1321）', verifiedDaily: true },
  { symbol: '1306', market: 'JP', shortLabel: 'TOPIX',
    fullLabel: 'TOPIX ETF（1306）', verifiedDaily: true },
  { symbol: 'SPY', market: 'US', shortLabel: 'S&P',
    fullLabel: 'S&P 500 ETF（SPY）', verifiedDaily: true },
  { symbol: 'QQQ', market: 'US', shortLabel: 'NASDAQ',
    fullLabel: 'Nasdaq 100 ETF（QQQ）', verifiedDaily: true },
] as const;

export const MARKET_HORIZONS: readonly MarketHorizon[] = [1, 5, 20];
export const DEFAULT_MARKET_INSTRUMENT: Record<MarketInstrumentMarket,
  MarketInstrumentSymbol> = { JP: '1321', US: 'SPY' };

export function marketInstrument(symbol: string | null | undefined) {
  const normalized = String(symbol ?? '').toUpperCase();
  return MARKET_INSTRUMENTS.find((item) => item.symbol === normalized) ?? null;
}

export function isVerifiedMarketInstrument(
  symbol: string | null | undefined,
  timeframe: 'daily' | 'weekly' = 'daily',
) {
  return timeframe === 'daily' && marketInstrument(symbol)?.verifiedDaily === true;
}

export function normalizeMarketInstrument(
  market: MarketInstrumentMarket,
  value: string | null | undefined,
): MarketInstrumentSymbol {
  const match = marketInstrument(value);
  return match?.market === market ? match.symbol : DEFAULT_MARKET_INSTRUMENT[market];
}
