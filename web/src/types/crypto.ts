// Mirrors the backend /api/argus/crypto-watchlist shape (CoinGecko, keyless).
// Quotes are keyed by CoinGecko id (e.g. "bitcoin") — the asset's memo stores
// the mapping as "coingecko:<id>". changePct is the 24h change.

export type CryptoQuoteStatus = 'live' | 'mock';

export interface CryptoQuote {
  id: string;            // coingecko id
  priceUsd: number;
  changePct: number;     // 24h %
  volume: number;        // 24h USD volume
  date: string | null;   // YYYY-MM-DD (last update)
  status: CryptoQuoteStatus;
}

export interface CryptoWatchlistSnapshot {
  status: 'live' | 'partial' | 'mock';
  asOf: string | null;
  provider: 'coingecko';
  quotes: CryptoQuote[];
}
