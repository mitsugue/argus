// 2026-10-18: expected dates against stored dates for each condition input.
// Counts and status only; the dates themselves stay in the admin diagnostics.
export type ReconciliationRow = { status: string; expected: number | null; actual: number | null;
  missing: number | null; unexpected: number | null; duplicated: number | null; invalidValues: number | null };
export type SeriesReconciliation = { measuredAt: string | null; series: Record<string, ReconciliationRow>; gapsFound: string[] };

export const SERIES_LABEL_JA: Record<string, string> = {
  'price_series:nikkei': '日経平均', 'price_series:topix': 'TOPIX', 'price_series:index_per': '日経平均PER（推計）',
  'two_market_credit': '二市場の信用残', 'foreign_flow': '海外投資家の売買', 'margin_1570': '1570の信用残',
  'price_series:sp500': 'S&P500', 'price_series:vix': 'VIX', 'price_series:us10y': '米10年金利',
  'price_series:usdjpy': 'ドル円', 'price_series:jp10y': '日本10年金利',
  'valuation_loss': '信用評価損益率（代理計算）', 'sq_events': 'SQの日程（規則で算出）',
};
export const STATUS_JA: Record<string, string> = {
  COMPLETE: '欠けなし', COMPLETE_WHERE_CALENDAR_KNOWN: '暦のある範囲で欠けなし', GAPS_FOUND: '欠け・余分あり',
  NO_ROWS: '保存なし', EXPECTED_CALENDAR_UNAVAILABLE: '公式の暦なし（照合しない）', NOT_EXPECTED: '照合対象外（算出・代理）',
};
const count = (v: unknown) => v === null || (Number.isSafeInteger(v) && (v as number) >= 0);
export function validSeriesReconciliation(v: unknown): v is SeriesReconciliation {
  if (!v || typeof v !== 'object') return false;
  const doc = v as Record<string, any>;
  if (!doc.series || typeof doc.series !== 'object' || !Array.isArray(doc.gapsFound)) return false;
  // A series this screen does not know yet is skipped, not a reason to hide the table.
  return Object.entries(doc.series).filter(([key]) => key in SERIES_LABEL_JA).every(([, row]) => !!row && typeof row === 'object'
    && typeof (row as any).status === 'string' && (row as any).status in STATUS_JA
    && ['expected', 'actual', 'missing', 'unexpected', 'duplicated', 'invalidValues'].every(f => count((row as any)[f])));
}
