/** 保存された原文は変えず、画面の時刻と定型表現だけを整える。 */
export function marketWording(text: string): string {
  return text.replace(/(\d{4}-\d{2}-\d{2})[T ・]+(\d{2}:\d{2})(?::\d{2})?Z/g, (_raw, day: string, time: string) => {
    const date = new Date(`${day}T${time}:00Z`);
    return Number.isFinite(date.getTime()) ? `${date.toLocaleString('ja-JP', {
      timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })}（日本時間）` : _raw;
  }).replaceAll('金融環境を通じて株式の重しとなる展開です', '株価の上昇を抑えることが懸念されています')
    .replaceAll('市場が期待する具体的な展開は、現在の根拠では確認できません。', '期待される展開を判断する根拠が不足しています。')
    .replaceAll('市場が警戒する具体的な展開は、現在の根拠では確認できません。', '警戒される展開を判断する根拠が不足しています。')
    .replaceAll('米金融政策の据え置きが続く展開', '米国の政策金利が変わらないこと')
    .replaceAll('据え置き観測が保たれる', '政策金利を変えないという市場の見方が続く')
    .replaceAll('長期金利の高止まり懸念が和らぎ', '長期金利が高いまま続くという懸念が弱まり')
    .replaceAll('弱気材料が優勢との整理はありますが、市場価格への影響は確認されていません。', '株価に不利とされる材料が多いものの、実際に株価へ影響したかは未確認です。');
}

export function hasSubstantiveView(text?: string): boolean {
  return !!text && !/現在の根拠では確認できません|判断する根拠が不足/.test(text);
}

type Explanation = { textJa: string; kind: 'FACT' | 'INFERENCE' | 'UNKNOWN' };

/** 現在表示する見出しだけを整える。保存された説明や当時の履歴は変えない。 */
export function marketHeadline(view?: Explanation, reasons?: Explanation): string | undefined {
  if (!view) return undefined;
  const text = marketWording(view.textJa);
  if (view.kind === 'UNKNOWN' || !/(?:見極める|見守る|注視する|確認する)(?:局面|段階|時期)/.test(text)
      || /(?:株価|日経平均|日本株).*(?:上が|下が|上昇|下落|抑え|支え)/.test(text)) return text;
  // 前の版の観察だけの主文には、同じ保存説明の理由にある影響の文を使う。
  // 根拠がない場合や長文しかない場合は、影響を新しく書き足さない。
  if (!reasons || reasons.kind === 'UNKNOWN') return text;
  const sentence = marketWording(reasons.textJa).match(/[^。！？]+[。！？]?/g)?.find(s =>
    s.length <= 80 && /(?:株価|日経平均|日本株).*(?:上が|下が|上昇|下落|押し上げ|抑え|支え)/.test(s));
  return sentence?.trim() || text;
}

export function marketChanges(text: string): string {
  if (text === '比較できる前回の見立てをまだ取得していません。') return '比較データなし';
  if (['前回からの市場の変化を示す、確認済みの観測はありません。',
    '前回から確認できた変化はありません。', '確認できた変化はありません。'].includes(text)) return 'なし';
  return marketWording(text);
}
