// 日米の強弱は日経平均そのものとS&P500そのものの比(日経平均÷S&P500)で見る(2026-10-23)。
// 両方の指数に終値がある日付だけでそろえ、比の20営業日の変化率(%)を返す。
// サーバーの relative_strength(nikkei_sp500) と同じ数え方。足りない時は null で、
// 1321 など他の系列で埋めない。
export interface DatedClose { date: string; close: number }

const closesByDate = (bars: readonly DatedClose[] | null | undefined): Map<string, number> => {
  const out = new Map<string, number>();
  for (const bar of bars ?? []) {
    const date = String(bar?.date ?? '').slice(0, 10);
    if (date.length === 10 && Number.isFinite(bar.close) && bar.close > 0) out.set(date, bar.close);
  }
  return out;
};

export function nikkeiSp500Change20Pct(nikkei: readonly DatedClose[] | null | undefined,
  sp500: readonly DatedClose[] | null | undefined): number | null {
  const jp = closesByDate(nikkei);
  const us = closesByDate(sp500);
  const ratios = Array.from(jp.keys()).sort()
    .filter((date) => us.has(date))
    .map((date) => jp.get(date)! / us.get(date)!);
  if (ratios.length <= 20) return null;
  return (ratios[ratios.length - 1] / ratios[ratios.length - 21] - 1) * 100;
}
