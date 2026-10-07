export type AnalystTarget = {
  symbol: string; market: 'JP' | 'US'; mean: number; median: number | null;
  high: number | null; low: number | null; analysts: number; currency: string | null;
  priceAtFetch: number | null; gapPct: number | null; fetchedAt: string; source: string;
  acquisitionStatus?: string;
};
const positive = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0;
export function validAnalystTarget(row: unknown, key: string): row is AnalystTarget {
  const r = row as AnalystTarget | null;
  return !!r && (r.market === 'JP' || r.market === 'US') && typeof r.symbol === 'string'
    && key === `${r.market}:${r.symbol.toUpperCase()}` && positive(r.mean)
    && Number.isInteger(r.analysts) && r.analysts > 0
    && typeof r.fetchedAt === 'string' && Number.isFinite(Date.parse(r.fetchedAt))
    && typeof r.source === 'string' && !!r.source
    && (r.currency === null || r.currency === (r.market === 'JP' ? 'JPY' : 'USD'));
}
export const outlookMoney = (value: number, market: string) => market === 'US'
  ? `$${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
  : `${Math.round(value).toLocaleString('ja-JP')}円`;
export function analystTargetGap(target: AnalystTarget, currentPrice: number | null): number | null {
  // Use the same displayed quote; never reuse Yahoo's price-at-fetch difference.
  return positive(currentPrice) ? (target.mean / currentPrice - 1) * 100 : null;
}
export const outlookDay = (iso: string | null | undefined) => {
  if (!iso) return '';
  // Preserve date-only observation days, including the JSF yyyy/mm/dd shape.
  const match = /^(\d{4})[-/](\d{2})[-/](\d{2})$/.exec(iso);
  if (match) return `${Number(match[2])}/${Number(match[3])}`;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('ja-JP', {
    timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' });
};

export const SUPPLY_RANK_TONE: Record<string, string> = {
  S: '#34d399', A: '#6ee7b7', B: '#67e8f9', C: '#e2e8f0', D: '#fbbf24', E: '#f87171', Unknown: '#94a3b8',
};
