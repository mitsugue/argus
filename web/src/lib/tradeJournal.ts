import { markLocalEdit } from './vault';
// My Trade Journal (trade-journal-v1, v10.23) — the user's OWN decisions,
// recorded WITH their rationale, so ARGUS can eventually score "your intuition
// vs the tool" (born from the 9984 @6450 trade, 2026-06-13). Device-local
// like holdings; synced via the encrypted vault (added to BACKUP_KEYS), never
// sent in plaintext. This is the human half of the learning loop.

const KEY = 'argus.trades.v1';
const MAX = 300;

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

function persist(list: TradeEntry[]): void {
  try { localStorage.setItem(KEY, JSON.stringify(list.slice(-MAX))); markLocalEdit(); } catch { /* ignore */ }
}

export function addTrade(t: Omit<TradeEntry, 'id' | 'createdAt' | 'status'>): TradeEntry {
  const entry: TradeEntry = {
    ...t, id: `${t.symbol}-${Date.now()}`, createdAt: Date.now(), status: 'open',
  };
  const list = readTrades();
  list.push(entry);
  persist(list);
  return entry;
}

export function closeTrade(id: string, exitPrice: number, exitDate: string): void {
  persist(readTrades().map((t) =>
    t.id === id ? { ...t, status: 'closed', exitPrice, exitDate } : t));
}

export function removeTrade(id: string): void {
  persist(readTrades().filter((t) => t.id !== id));
}

/** Unrealized (open) or realized (closed) P/L % for a trade vs a live price. */
export function tradePnlPct(t: TradeEntry, livePrice: number | undefined): number | null {
  const ref = t.status === 'closed' ? t.exitPrice : livePrice;
  if (ref == null || !t.price) return null;
  const raw = (ref - t.price) / t.price * 100;
  return Math.round((t.side === 'buy' ? raw : -raw) * 100) / 100;
}
