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
