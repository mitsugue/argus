// ARGUS V11.5.1/V11.5.2 — AI explanation display state (pure). AI explanations are
// generated only by the admin/cron (never on a public click). This maps the status to
// what the UI shows so we NEVER render a dead "AI解説を表示" button. V11.5.2 adds the
// 「理由を詳しく調べる」 action for the not_generated state — clicking it ENQUEUES a request
// (POST explain-request), it does NOT start AI from the public page.

export type AiExplanationStatus =
  | 'cached' | 'queued' | 'pending' | 'generating' | 'not_generated'
  | 'disabled' | 'budget_limited' | 'error' | 'rate_limited';

export interface AiExplanationDisplay {
  status: AiExplanationStatus;
  // expandable=open cached text; request=clickable "調べる" (queues only); chip/text=non-clickable
  mode: 'expandable' | 'request' | 'chip' | 'text';
  labelJa: string;
  noteJa: string;
}

const SHORT_NOTE = 'AI解説は、重要度の高い値動きから順にバックグラウンドで生成されます。';
const DETAIL_NOTE = '公開画面のクリックではAIを起動しません。コストと安全性のため、管理側の定期実行で生成済みの解説だけを表示します。';

/** Resolve the display from the explanation text + status. A present explanation
 *  always wins (cached); otherwise the status decides the (non-AI-triggering) action. */
export function aiExplanationDisplay(
  explanationJa?: string | null,
  status?: AiExplanationStatus | string | null,
): AiExplanationDisplay {
  if (explanationJa && explanationJa.trim()) {
    return { status: 'cached', mode: 'expandable', labelJa: 'AI解説を開く', noteJa: '生成済みのAI解説' };
  }
  const s = (status as AiExplanationStatus) || 'not_generated';
  switch (s) {
    case 'queued':
      return { status: 'queued', mode: 'chip', labelJa: '調査リクエスト済み',
        noteJa: `次回の自動生成で反映されます。${DETAIL_NOTE}` };
    case 'pending':
    case 'generating':
      return { status: s, mode: 'chip', labelJa: 'AI解説は生成待ち',
        noteJa: `重要度の高い銘柄から定期生成します。${DETAIL_NOTE}` };
    case 'budget_limited':
      return { status: 'budget_limited', mode: 'chip', labelJa: '予算上限のため保留', noteJa: DETAIL_NOTE };
    case 'disabled':
      return { status: 'disabled', mode: 'chip', labelJa: 'AI解説は停止中', noteJa: DETAIL_NOTE };
    case 'error':
      return { status: 'error', mode: 'chip', labelJa: 'AI解説生成に失敗', noteJa: '次回の定期生成で再試行します。' };
    case 'rate_limited':
      return { status: 'rate_limited', mode: 'request', labelJa: '理由を詳しく調べる',
        noteJa: 'リクエストが混み合っています。少し待って再度お試しください。' };
    case 'cached':   // status says cached but no text → treat as not-yet-available
    case 'not_generated':
    default:
      // V11.5.2: a real, safe action — enqueue an investigation (no public AI start).
      return { status: 'not_generated', mode: 'request', labelJa: '理由を詳しく調べる',
        noteJa: `公開画面からAIは起動しません。調査キューへ追加します。${SHORT_NOTE}` };
  }
}

/** Preferred visible news headline: always Japanese (or a JP fallback), never raw
 *  English. Falls back through displayTitleJa → titleJa(if Japanese) → placeholder. */
export function newsDisplayTitleJa(n: {
  displayTitleJa?: string; titleJa?: string; titleOriginal?: string;
  translationStatus?: string; source?: string;
}): string {
  if (n.displayTitleJa && n.displayTitleJa.trim()) return n.displayTitleJa;
  // legacy items without displayTitleJa: only use titleJa if it isn't English.
  const t = n.titleJa || '';
  const looksEnglish = /[A-Za-z]/.test(t) && !/[぀-ヿ㐀-䶵一-鿋]/.test(t);
  if (t && !looksEnglish) return t;
  const src = (n.source || '').trim();
  return `翻訳待ち: ${src ? src + 'の' : ''}関連ニュース`;
}
