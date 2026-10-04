/** 保存された原文は変えず、画面の時刻と定型表現だけを整える。 */
export function marketWording(text: string): string {
  return text.replace(/(\d{4}-\d{2}-\d{2})[T ・]+(\d{2}:\d{2})(?::\d{2})?Z/g, (_raw, day: string, time: string) => {
    const date = new Date(`${day}T${time}:00Z`);
    return Number.isFinite(date.getTime()) ? `${date.toLocaleString('ja-JP', {
      timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })}（日本時間）` : _raw;
  }).replaceAll('金融環境を通じて株式の重しとなる展開です', '株価の上昇を抑えることが懸念されています')
    .replaceAll('市場が期待する具体的な展開は、現在の根拠では確認できません。', '期待される展開を判断する根拠が不足しています。')
    .replaceAll('市場が警戒する具体的な展開は、現在の根拠では確認できません。', '警戒される展開を判断する根拠が不足しています。');
}

export function hasSubstantiveView(text?: string): boolean {
  return !!text && !/現在の根拠では確認できません|判断する根拠が不足/.test(text);
}
