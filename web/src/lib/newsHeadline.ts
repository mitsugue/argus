// v13.5.61 (owner iPhone review 2026-09-07): a Nikkei digest mail arrives as
// 「日経ニュースメール 9/7 夕版 ━ 注目ニュース ━━━━━━━ ◆円半年ぶりに…」. The mail
// header is not the news. For DISPLAY only, keep the first headline after the
// first ◆ marker; the stored event text is untouched (evidence stays verbatim).
export function displayNewsHeadline(raw: string | null | undefined): string {
  // Strip only the known delivery notice after a mail separator. An article
  // about the app itself must remain intact; stored evidence is never edited.
  const text = String(raw ?? '').trim().replace(
    /\s*[━─―—－-]{3,}\s*■?\s*日経電子版アプリのプッシュ通知でも速報を受け取れます[\s\S]*$/u,
    '',
  ).trim();
  if (!text) return '';
  const marker = text.indexOf('◆');
  if (marker < 0) return text;
  const body = text.slice(marker + 1).trim();
  if (!body) return text;
  // the digest joins several items with further ◆ markers; show only the first
  const next = body.indexOf('◆');
  const first = (next > 0 ? body.slice(0, next) : body).trim();
  return first.replace(/[（(]有料会員限定[）)]/g, '').trim() || text;
}

/** A digest headline (mail header before ◆) is not a single news item. */
export function isDigestHeadline(raw: string | null | undefined): boolean {
  const text = String(raw ?? '');
  return /ニュースメール/.test(text) && text.includes('◆');
}


export function newsAnalysisStatusJa(state: string | null | undefined, scope?: string): string {
  return state === 'ANALYZED' ? (scope === 'stored_headline_only' ? '見出しのAI解析済み・本文未確認' : 'AI解析済み')
    : state === 'AI_CACHED' ? '保存済み解析を参照'
      : '詳細AI解析未完了・規則による判定';
}
