// 2026-11-13 (owner: 「朝８時にSQの通知は来てません」): the delivery records in
// Settings named only their state, so an SQ notice could not be told from a
// news or price notice. The server's own record key says which notice it was;
// no notice content is read.
const SQ_PHASES: Record<string, string> = { DAY: '当日', PREVIOUS_SESSION: '最終取引日', WEEK: '週の案内' };

export function pushRecordKindJa(key: unknown): string {
  if (typeof key !== 'string') return '通知';
  const sq = /^jp-monthly-sq-\d{4}-(\d{2}):(DAY|PREVIOUS_SESSION|WEEK)$/.exec(key);
  if (sq) return `${Number(sq[1])}月のSQ・${SQ_PHASES[sq[2]]}`;
  if (key.startsWith('news:fiscal:')) return '財政・金利の警戒変化';
  if (key.startsWith('news:')) return '重大ニュース';
  if (key.startsWith('owner-change:')) return '監視銘柄の急騰・急落';
  if (key.startsWith('test:')) return '確認通知';
  return '通知';
}

/** The server's send time (epoch seconds), or 未送信 before any attempt. */
export function pushRecordSentJa(attempted: unknown): string {
  return typeof attempted === 'number' && Number.isFinite(attempted) && attempted > 0
    ? new Date(attempted * 1000).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }) : '未送信';
}
