// v13.5.49 — Japanese titles for important macro events.
//
// The backend calendar carries English titles (source vocabulary). The
// owner-facing surface must name important events in Japanese, so titles are
// mapped deterministically by event code and by well-known title patterns.
// Unknown titles fall back to the original English text (never invented).
const CODE_JA: Record<string, string> = {
  NFP: '米雇用統計', CPI: '米消費者物価指数(CPI)', PPI: '米生産者物価指数(PPI)', PCE: '米PCE物価指数',
  FOMC: 'FOMC(米政策金利)', BOJ: '日銀金融政策決定会合', ECB: 'ECB理事会', BOE: '英中銀政策会合',
  JOLTS: '米求人件数(JOLTS)', GDP: '米GDP', ISM: '米ISM景況指数', RETAIL: '米小売売上高',
  AUCTION: '米国債入札', EARNINGS: '決算', CLAIMS: '米新規失業保険申請', UMICH: 'ミシガン大消費者信頼感',
  TANKAN: '日銀短観', JPCPI: '日本CPI', JPGDP: '日本GDP',
};

const PATTERNS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/^US Treasury (\d+)-Year Auction$/i, (m) => `米${m[1]}年債入札`],
  [/^US Treasury (\d+)-Month Bill Auction$/i, (m) => `米${m[1]}カ月物短期国債入札`],
  [/^US Employment Situation$/i, () => '米雇用統計'],
  [/^US PCE/i, () => '米PCE物価指数(個人所得・支出)'],
  [/^US CPI/i, () => '米消費者物価指数(CPI)'],
  [/^US PPI/i, () => '米生産者物価指数(PPI)'],
  [/^US Retail Sales/i, () => '米小売売上高'],
  [/^US GDP/i, () => '米GDP'],
  [/^US JOLTS/i, () => '米求人件数(JOLTS)'],
  [/^ISM (Manufacturing|Services)/i, (m) => `米ISM${m[1].toLowerCase() === 'manufacturing' ? '製造業' : '非製造業'}景況指数`],
  [/^FOMC/i, () => 'FOMC(米政策金利)'],
  [/^(BOJ|Bank of Japan)/i, () => '日銀金融政策決定会合'],
  [/^ECB/i, () => 'ECB理事会'],
  [/^Initial Jobless Claims/i, () => '米新規失業保険申請件数'],
  [/^University of Michigan/i, () => 'ミシガン大消費者信頼感指数'],
  [/^Japan CPI/i, () => '日本消費者物価指数(CPI)'],
  [/^Japan GDP/i, () => '日本GDP'],
  [/^Tankan/i, () => '日銀短観'],
];

const JA_CHARS = /[぀-ヿ一-鿿]/;

/** Japanese title for an important event; the English title only when nothing maps. */
export function eventTitleJa(eventCode: string | null | undefined, title: string | null | undefined): string {
  const raw = (title ?? '').trim();
  if (JA_CHARS.test(raw)) return raw;
  for (const [pattern, render] of PATTERNS) {
    const match = raw.match(pattern);
    if (match) return render(match);
  }
  const code = (eventCode ?? '').toUpperCase();
  if (CODE_JA[code]) return CODE_JA[code];
  return raw;
}

export function eventTitleIsJapanese(title: string | null | undefined): boolean {
  return JA_CHARS.test((title ?? '').trim());
}
