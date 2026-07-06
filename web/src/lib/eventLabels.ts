// Shared event-label vocabulary so the Market Context page speaks the SAME language
// as the top-page IMPORTANT EVENTS card (v10.162). Impact = how strongly markets may
// move (violet/amber/blue/gray — NEVER price red/green), never a direction.

export const IMPACT_TOKEN: Record<string, string> = {
  critical: 'var(--event-critical)', high: 'var(--event-high)',
  medium: 'var(--event-medium)', low: 'var(--event-low)',
};
export const IMPACT_ICON: Record<string, string> = { critical: '◆', high: '▲', medium: '●', low: '·' };
export const IMPACT_JA: Record<string, string> = { critical: '重大', high: '大', medium: '中', low: '小' };

// Proximity, matching the top card's wording.
export const COUNTDOWN_JA: Record<string, string> = {
  D: '本日', 'D-1': '明日', 'D-3': '数日内', 'D-7': '1週間内', 'D+1': '昨日', normal: '予定',
};

// Plain-Japanese countdown from a day offset (top card uses date + これ).
export function whenJa(daysUntil: number, stamp?: string | null): string {
  const rel = daysUntil === 0 ? '本日' : daysUntil === 1 ? '明日' : daysUntil === -1 ? '昨日'
    : daysUntil < 0 ? `${-daysUntil}日前` : `あと${daysUntil}日`;
  return stamp ? `${rel} · ${stamp}` : rel;
}

export const CATEGORY_JA: Record<string, string> = {
  central_bank: '中央銀行', inflation: 'インフレ', jobs: '雇用', growth: '成長', treasury: '国債',
};

// v12.0.4 (owner request): 「どんなイベントか」の一言概要 — トップカードの各行に表示。
// 初心者が読める平易な説明のみ(予測・方向は書かない)。未知コードは表示なし。
export const EVENT_DESC_JA: Record<string, string> = {
  NFP: '米国の雇用者数・失業率の月次発表。金利と株全体が動きやすい',
  CPI: '米国の消費者物価(インフレ)の月次発表。利下げ/利上げ観測を左右',
  PPI: '米国の生産者物価。CPIの先行ヒントとして見られる',
  PCE: 'FRBが最重視するインフレ指標。金利観測に直結',
  FOMC: '米国の政策金利を決める会合。声明と会見で相場が大きく動く',
  BOJ: '日銀の金融政策決定会合。円金利・ドル円・日本株に直結',
  BOE: '英中銀の政策金利決定',
  ECB: '欧州中銀の政策金利決定',
  AUCTION: '米国債の入札。需要が弱いと金利上昇→株の逆風になりやすい',
  GDP: '経済成長率の発表。景気の強弱を確認する材料',
  JOLTS: '米国の求人件数。雇用の過熱/減速のヒント',
  EARNINGS: '企業決算。ガイダンス次第で個別・セクターが大きく動く',
};
