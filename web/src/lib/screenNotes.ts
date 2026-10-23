// Owner policy 2026-10-23 (AGENTS.md「画面の言葉とデザインの基本方針」): server
// texts carry disclaimer sentences ("…ではありません", "予測力は未検証") that the
// screen does not show. Only whole sentences that are such a note are dropped;
// numbers, dates and every other sentence stay exactly as received.
const NOTE_SENTENCES: RegExp[] = [
  // "〜は予測・確率・売買の合図・判定ではありません"
  /(予測|確率|的中|売買|買い|売り|合図|サイン|判定|指示|推奨|検証結果|権限|保証)[^。]*(ではありません|ではない)$/,
  // "予測力は未検証" / "どれも単独では予測力を確かめていません" / "将来の予測力を保証しません"
  /予測力[^。]*(未検証|確かめていません|保証しません|ありません)/,
  /^(過去の頻度であり確率ではありません|売買根拠への自動昇格なし|観測値からの記述計算であり、予測力は未検証)$/,
  // "実際の買い戻し注文は未観測" / "現在の建玉は未観測" / "業種全体の資金流入とは未確認"
  /(注文|建玉)は未観測$/, /とは未確認$/,
];

/** The text without its disclaimer sentences. */
export function withoutScreenNotes(text: string): string {
  if (typeof text !== 'string' || !text) return text;
  const sentences = text.split(/(?<=。)/);
  const kept = sentences.filter(sentence => {
    const body = sentence.replace(/。$/, '').trim();
    return !body || !NOTE_SENTENCES.some(pattern => pattern.test(body));
  });
  return kept.join('').trim();
}
