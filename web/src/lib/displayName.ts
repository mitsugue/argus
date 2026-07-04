// v11.12.1 — 恒久ルール(オーナー指示 2026-07-04):
// 日本株は如何なる場所でも「数字+会社名(長い場合は省略)」で並記する。
// 9984 だけでは読めない — 「9984 ソフトバンクG…」と出す。
// 新しいセクション/カード/コピー文を作る時は必ずこのヘルパーを通すこと。

const MAX_NAME = 8;

/** 会社名を最大8文字に省略(9984 ソフトバンクグ… 形式)。 */
export function shortNameJa(name: string | null | undefined): string {
  const n = (name ?? '').trim();
  if (!n) return '';
  return n.length > MAX_NAME ? `${n.slice(0, MAX_NAME)}…` : n;
}

/** JP(数字始まり)は「コード 社名」、それ以外はシンボルのまま。
 *  name が無い/コードと同じ場合はシンボルのみ(捏造しない)。 */
export function jpDisplay(symbol: string, name?: string | null): string {
  const sym = (symbol ?? '').trim();
  if (!/^\d/.test(sym)) return sym;                    // US/crypto — code is readable
  const n = shortNameJa(name);
  return n && n !== sym ? `${sym} ${n}` : sym;
}
