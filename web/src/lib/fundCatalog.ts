// Curated JP mutual-fund catalog (v10.1). Non-listed 投信 are NOT in J-Quants
// (it only covers listed securities), so the Add-Asset dialog searches this
// LOCAL list — no API, no NAV claim. Names are official product names; add new
// entries here as needed. NAV (基準価額) live data remains a future source.

export interface FundEntry {
  slug: string;        // becomes the asset symbol (stable id)
  nameJa: string;      // official fund name
  nameEn?: string;
  keywords: string[];  // lowercase match helpers (brand, nicknames, indices)
}

export const FUND_CATALOG: FundEntry[] = [
  { slug: 'EMAXIS-ACWI',        nameJa: 'eMAXIS Slim 全世界株式（オール・カントリー）', nameEn: 'eMAXIS Slim All Country', keywords: ['emaxis', 'slim', 'オルカン', '全世界', 'オールカントリー', 'all country', 'acwi'] },
  { slug: 'EMAXIS-SP500',       nameJa: 'eMAXIS Slim 米国株式（S&P500）', nameEn: 'eMAXIS Slim US Equity (S&P500)', keywords: ['emaxis', 'slim', 'sp500', 's&p500', '米国株式', '米国'] },
  { slug: 'EMAXIS-ACWI-EXJP',   nameJa: 'eMAXIS Slim 全世界株式（除く日本）', keywords: ['emaxis', 'slim', '全世界', '除く日本'] },
  { slug: 'EMAXIS-DEV',         nameJa: 'eMAXIS Slim 先進国株式インデックス', keywords: ['emaxis', 'slim', '先進国'] },
  { slug: 'EMAXIS-EM',          nameJa: 'eMAXIS Slim 新興国株式インデックス', keywords: ['emaxis', 'slim', '新興国'] },
  { slug: 'EMAXIS-TOPIX',       nameJa: 'eMAXIS Slim 国内株式（TOPIX）', keywords: ['emaxis', 'slim', 'topix', '国内株式'] },
  { slug: 'EMAXIS-N225',        nameJa: 'eMAXIS Slim 国内株式（日経平均）', keywords: ['emaxis', 'slim', '日経', 'nikkei', '国内株式'] },
  { slug: 'EMAXIS-BAL8',        nameJa: 'eMAXIS Slim バランス（8資産均等型）', keywords: ['emaxis', 'slim', 'バランス', '8資産'] },
  { slug: 'EMAXIS-DEVBOND',     nameJa: 'eMAXIS Slim 先進国債券インデックス', keywords: ['emaxis', 'slim', '先進国', '債券'] },
  { slug: 'EMAXIS-JPBOND',      nameJa: 'eMAXIS Slim 国内債券インデックス', keywords: ['emaxis', 'slim', '国内', '債券'] },
  { slug: 'EMAXIS-NASDAQ100',   nameJa: 'eMAXIS NASDAQ100インデックス', keywords: ['emaxis', 'nasdaq', 'ナスダック'] },
  { slug: 'SBI-V-SP500',        nameJa: 'SBI・V・S&P500インデックス・ファンド', keywords: ['sbi', 'sp500', 's&p500', 'バンガード'] },
  { slug: 'SBI-V-VTI',          nameJa: 'SBI・V・全米株式インデックス・ファンド', keywords: ['sbi', '全米', 'vti'] },
  { slug: 'SBI-V-VT',           nameJa: 'SBI・V・全世界株式インデックス・ファンド', keywords: ['sbi', '全世界', 'vt'] },
  { slug: 'SBI-YUKIDARUMA',     nameJa: 'SBI・全世界株式インデックス・ファンド（雪だるま）', keywords: ['sbi', '雪だるま', '全世界'] },
  { slug: 'RAKUTEN-VTI',        nameJa: '楽天・全米株式インデックス・ファンド（楽天・VTI）', keywords: ['楽天', 'rakuten', 'vti', '全米'] },
  { slug: 'RAKUTEN-VT',         nameJa: '楽天・全世界株式インデックス・ファンド（楽天・VT）', keywords: ['楽天', 'rakuten', 'vt', '全世界'] },
  { slug: 'RAKUTEN-SP500',      nameJa: '楽天・S&P500インデックス・ファンド', keywords: ['楽天', 'rakuten', 'sp500', 's&p500'] },
  { slug: 'NISSAY-GAIKOKU',     nameJa: '＜購入・換金手数料なし＞ニッセイ外国株式インデックスファンド', keywords: ['ニッセイ', 'nissay', '外国株式', '先進国'] },
  { slug: 'NISSAY-TOPIX',       nameJa: '＜購入・換金手数料なし＞ニッセイTOPIXインデックスファンド', keywords: ['ニッセイ', 'nissay', 'topix'] },
  { slug: 'IFREE-SP500',        nameJa: 'iFree S&P500インデックス', keywords: ['ifree', 'sp500', 's&p500', '大和'] },
  { slug: 'IFREENEXT-FANGPLUS', nameJa: 'iFreeNEXT FANG+インデックス', keywords: ['ifree', 'fang', 'ファング'] },
  { slug: 'IFREENEXT-NASDAQ',   nameJa: 'iFreeNEXT NASDAQ100インデックス', keywords: ['ifree', 'nasdaq', 'ナスダック'] },
  { slug: 'TAWARA-DEV',         nameJa: 'たわらノーロード 先進国株式', keywords: ['たわら', 'tawara', '先進国'] },
  { slug: 'HIFUMI-PLUS',        nameJa: 'ひふみプラス', keywords: ['ひふみ', 'hifumi', 'レオス'] },
  { slug: 'SAISON-GBAL',        nameJa: 'セゾン・グローバルバランスファンド', keywords: ['セゾン', 'saison', 'バランス', 'グローバル'] },
];

function norm(s: string): string {
  return s.toLowerCase().replace(/[\s・（）()<>＜＞&＆.]/g, '');
}

/** Local fuzzy-ish search: matches slug / official name / keywords. */
export function searchFunds(q: string, max = 10): FundEntry[] {
  const nq = norm(q);
  if (!nq) return [];
  return FUND_CATALOG.filter((f) =>
    norm(f.slug).includes(nq) ||
    norm(f.nameJa).includes(nq) ||
    (f.nameEn ? norm(f.nameEn).includes(nq) : false) ||
    f.keywords.some((k) => norm(k).includes(nq) || nq.includes(norm(k)))
  ).slice(0, max);
}
