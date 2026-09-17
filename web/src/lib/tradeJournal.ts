// Archived user records are read-only. The existing backup key is preserved.

const KEY = 'argus.trades.v1';

export interface TradeEntry {
  id: string;
  symbol: string;
  name: string;
  market: 'JP' | 'US' | 'CRYPTO' | 'CORE';
  side: 'buy' | 'sell';
  price: number;            // entry price (per share/unit, in the asset's currency)
  qty: number | null;       // optional size
  date: string;             // JST YYYY-MM-DD of entry
  rationaleJa: string;      // WHY — the user's own reasoning
  argusNote?: string;       // optional snapshot of ARGUS's read at entry
  status: 'open' | 'closed';
  exitPrice?: number | null;
  exitDate?: string | null;
  createdAt: number;
}

export function readTrades(): TradeEntry[] {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? (JSON.parse(raw) as TradeEntry[]) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}
