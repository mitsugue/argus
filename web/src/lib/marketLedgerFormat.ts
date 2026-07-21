import type { MarketLedgerBacktestSummary } from '../types/marketLedger';

/** Format both legacy string summaries and the structured walk-forward result. */
export function formatOutcomeSummary(summary: string | MarketLedgerBacktestSummary | null | undefined): string {
  if (typeof summary === 'string') return summary;
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return 'insufficient_data';
  const parts: string[] = [];
  if (typeof summary.hitRate5d === 'number') parts.push(`5日hit ${(summary.hitRate5d * 100).toFixed(1)}%`);
  if (typeof summary.average5dPct === 'number') parts.push(`平均5日 ${summary.average5dPct.toFixed(2)}%`);
  if (typeof summary.maxDrawdownPct === 'number') parts.push(`最大下落 ${summary.maxDrawdownPct.toFixed(2)}%`);
  if (summary.noFutureLeakage === true) parts.push('future leakageなし');
  return parts.length ? parts.join(' · ') : 'insufficient_data';
}
