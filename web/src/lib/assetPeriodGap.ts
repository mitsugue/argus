// 2026-11-13 (N11: 指数と業種・登録銘柄の評価が違う理由を母集団と期間つきで).
// The stock page showed only the gap to the Nikkei; the same market-internals
// frame also holds the gap to the stock's own sector and the exact period.
export type AssetPeriodRow = {
  relativeToNikkeiPct: number | null; relativeToSectorPct: number | null;
  sectorNameJa: string | null; startDate: string; endDate: string;
};

const pct = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
const day = (iso: string) => /^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}` : null;

/** One line: 日経との差 -7.49% · 鉄鋼・非鉄との差 -8.33%（11/5〜11/12・5営業日）, or null. */
export function assetPeriodGapJa(row: AssetPeriodRow | null | undefined, sessions: number): string | null {
  if (!row) return null;
  const parts: string[] = [];
  if (row.relativeToNikkeiPct != null && Number.isFinite(row.relativeToNikkeiPct)) parts.push(`日経との差 ${pct(row.relativeToNikkeiPct)}`);
  if (row.relativeToSectorPct != null && Number.isFinite(row.relativeToSectorPct) && row.sectorNameJa)
    parts.push(`${row.sectorNameJa}との差 ${pct(row.relativeToSectorPct)}`);
  if (!parts.length) return null;
  const start = day(row.startDate), end = day(row.endDate);
  const span = start && end ? `${start}〜${end}・${sessions}営業日` : `${sessions}営業日`;
  return `${parts.join(' · ')}（${span}）`;
}
