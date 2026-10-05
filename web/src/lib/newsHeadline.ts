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
  const range = scope === 'mail_headline_and_bounded_excerpt' ? '見出し・抜粋を解析' : scope === 'stored_headline_only' ? '見出しを解析・本文未確認' : '解析範囲は未確認';
  return state === 'ANALYZED' ? range
    : state === 'AI_CACHED' ? `${range}（保存分）`
      : state === 'DETERMINISTIC_ONLY' ? 'AI未実行・規則による分類'
      : '詳細AI解析未完了・規則による判定';
}

/** 一覧の読取り成功と、メールの新着確認成功を混同しない。 */
export function newsIntakeHealthJa(health: { status:string; lastSyncAt:string|null; configured:boolean; threadAlive:boolean; pending:number } | null | undefined, now = Date.now()) {
  if (!health) return '取り込み状態は未確認';
  if (!health.configured) return 'ニュースの取り込み未設定';
  if (!health.threadAlive) return '取り込み処理が停止中';
  if (health.status !== 'HEALTHY') return '取り込みに不具合があります';
  const at = Date.parse(health.lastSyncAt ?? '');
  if (!Number.isFinite(at) || at > now + 300000) return '取り込み時刻は未確認';
  if (now - at > 15 * 60000) return '新着確認が15分以上遅れています';
  return health.pending > 0 ? `新着 ${health.pending}件を整理中` : '新着を確認済み';
}
