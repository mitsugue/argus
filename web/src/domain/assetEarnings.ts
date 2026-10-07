export type AssetEarnings = {
  symbol: string; market: 'JP' | 'US'; source: string; fetchedAt: string; currency: string | null;
  actionAuthority: false; acquisitionStatus?: string; companyStatus?: string;
  next: { from: string; to: string; certainty: 'PROVIDER_ESTIMATE'; timezone: string } | null;
  previous: { currency?: string | null; periodEnd: string; epsActual: number; epsEstimate: number | null; surprisePct: number | null } | null;
  estimate: { epsCurrency?: string | null; revenueCurrency?: string | null; periodEnd: string; eps: number | null; epsLow: number | null; epsHigh: number | null;
    analysts: number | null; epsGrowthPct: number | null; revenue: number | null; revenueAnalysts: number | null;
    revenueGrowthPct: number | null; eps30DaysAgo: number | null } | null;
  company?: { disclosedDate: string; periodEnd: string | null; periodType: string; fiscalYearEnd: string | null;
    operatingProfit: number; forecastOperatingProfit: number | null; consolidated: boolean;
    source: string; currency: 'JPY'; receivedAt: string };
};
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const optionalNumber = (value: unknown) => value === null || finite(value);
const unit = (value: unknown) => value === undefined || value === null || typeof value === 'string' && /^[A-Z]{3}$/.test(value);
const count = (value: unknown) => value === null || finite(value) && Number.isInteger(value) && value >= 1;
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 100;
export const validEarningsDay = (value: unknown): value is string => typeof value === 'string' &&
  /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
export function validAssetEarnings(value: unknown, key: string): value is AssetEarnings {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const row = value as AssetEarnings;
  if (!['JP', 'US'].includes(row.market) || key !== `${row.market}:${row.symbol}` || !text(row.symbol) ||
    !text(row.source) || !text(row.fetchedAt) || !Number.isFinite(Date.parse(row.fetchedAt)) || row.actionAuthority !== false ||
    !(row.currency === null || typeof row.currency === 'string' && /^[A-Z]{3}$/.test(row.currency))) return false;
  const n = row.next, p = row.previous, e = row.estimate, c = row.company;
  if (n !== null && (!n || !validEarningsDay(n.from) || !validEarningsDay(n.to) || n.from > n.to ||
    n.certainty !== 'PROVIDER_ESTIMATE' || n.timezone !== (row.market === 'JP' ? 'Asia/Tokyo' : 'America/New_York'))) return false;
  if (p !== null && (!p || !validEarningsDay(p.periodEnd) || !finite(p.epsActual) ||
    !unit(p.currency) || !optionalNumber(p.epsEstimate) || !optionalNumber(p.surprisePct))) return false;
  if (e !== null && (!e || !validEarningsDay(e.periodEnd) || !unit(e.epsCurrency) || !unit(e.revenueCurrency) || !count(e.analysts) || !count(e.revenueAnalysts) ||
    ![e.eps, e.epsLow, e.epsHigh, e.epsGrowthPct, e.revenue, e.revenueGrowthPct, e.eps30DaysAgo].every(optionalNumber) ||
    e.eps !== null && e.analysts === null || e.revenue !== null && e.revenueAnalysts === null)) return false;
  if (c !== undefined && (!c || row.market !== 'JP' || !validEarningsDay(c.disclosedDate) ||
    !(c.periodEnd === null || validEarningsDay(c.periodEnd)) || !(c.fiscalYearEnd === null || validEarningsDay(c.fiscalYearEnd)) ||
    !finite(c.operatingProfit) || !optionalNumber(c.forecastOperatingProfit) || typeof c.consolidated !== 'boolean' ||
    !text(c.periodType) || !text(c.source) || c.currency !== 'JPY' || !text(c.receivedAt) || !Number.isFinite(Date.parse(c.receivedAt)))) return false;
  return !!(n || p || e || c);
}
export function earningsToday(row: AssetEarnings, now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en', { timeZone: row.market === 'JP' ? 'Asia/Tokyo' : 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)?.value).join('-');
}
export function earningsDateLabel(row?: AssetEarnings, now = new Date()): string {
  if (!row?.next || row.next.to < earningsToday(row, now)) return '次回決算 日付未取得';
  const short = (day: string) => `${Number(day.slice(5, 7))}/${Number(day.slice(8, 10))}`;
  const dates = row.next.from === row.next.to ? short(row.next.from) : `${short(row.next.from)}〜${short(row.next.to)}`;
  return `次回決算 ${dates}（推定${row.market === 'US' ? '・米東部' : ''}）`;
}
export function earningsAmount(value: number, currency: string | null): string {
  if (!currency) return `${value.toLocaleString('ja-JP', { maximumFractionDigits: 2 })}（通貨未確認）`;
  return new Intl.NumberFormat('ja-JP', { style: 'currency', currency, maximumFractionDigits: 2 }).format(value);
}
export const earningsPct = (value: number): string => `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
