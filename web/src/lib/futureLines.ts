// Future lines (2026-10-19, owner decision): weekly pre-recorded paths of the
// Nikkei — a video commentary's drawn path, two mechanical paths and a public
// wave-count view — with one fixed scoring rule. Shown without source names.
export type FuturePoint = { kind: 'H' | 'L'; date: string; price: number };
export type FutureLine = { rec: string; recordedAt: string; eps: number | null; points: FuturePoint[] };
export type Measure = { hit: number; n: number; pending: number; randomMean: number | null } | null;
export type LineRecord = { records: number; strict: Measure; standard: Measure; loose: Measure; timing: Measure;
  reach: { reach: number; stop: number; expire: number; pending: number; 'n/a': number } };
export type FutureLinesDoc = {
  schemaVersion: 'argus-future-lines-public-v1'; availability: 'AVAILABLE'; updatedAt: string; dataEnd: string;
  lines: Partial<Record<LineId, FutureLine | null>>; history: Partial<Record<LineId, FutureLine[]>>;
  wave: { pub: string; recordedAt: string; dir: 'up' | 'down'; target: number; stop: number; result: string; settledBeforeRecord: boolean } | null;
  record: Partial<Record<LineId, LineRecord>> & { wave?: { records: number; reach: number; n: number; pending: number } };
  retroRecord: Partial<Record<LineId, LineRecord>>; closes: { date: string; close: number }[];
  actionAuthority: false; argusValidated: false;
};
export type LineId = 'commentator' | 'machine' | 'machine2';
// 2026-10-25 (owner): shorter names on the simplified view.
export const LINE_LABEL: Record<LineId, string> = { commentator: '動画の線', machine: '2018年の暦', machine2: '山谷の間隔' };
export const MEASURE_LABEL: Record<'strict' | 'standard' | 'loose' | 'timing', string> = {
  strict: '厳しい（5%の山谷・±5営業日・±2%）', standard: '標準（4%・±7営業日・±3%）', loose: 'ゆるい（3%・±10営業日・±4%）', timing: '時期だけ（4%・±5営業日）' };

const day = (v: unknown) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v);
const num = (v: unknown) => typeof v === 'number' && Number.isFinite(v);
function validLine(v: unknown): v is FutureLine {
  const l = v as FutureLine;
  return !!l && day(l.rec) && typeof l.recordedAt === 'string' && Array.isArray(l.points) && l.points.length > 0
    && l.points.every((p, i) => (p.kind === 'H' || p.kind === 'L') && day(p.date) && p.date > l.rec && num(p.price) && p.price > 0
      && (i === 0 || p.date > l.points[i - 1].date));
}

export function validFutureLines(value: unknown): value is FutureLinesDoc {
  const d = value as FutureLinesDoc;
  if (!d || d.schemaVersion !== 'argus-future-lines-public-v1' || d.availability !== 'AVAILABLE' || d.actionAuthority !== false) return false;
  if (!d.lines || typeof d.lines !== 'object' || !Array.isArray(d.closes)) return false;
  if (!Object.entries(d.lines).every(([k, l]) => k in LINE_LABEL && (l === null || validLine(l)))) return false;
  if (!Object.entries(d.history || {}).every(([k, rows]) => k in LINE_LABEL && Array.isArray(rows) && rows.every(validLine))) return false;
  if (d.wave && !(day(d.wave.pub) && num(d.wave.target) && num(d.wave.stop) && (d.wave.dir === 'up' ? d.wave.target > d.wave.stop : d.wave.target < d.wave.stop))) return false;
  return d.closes.every(c => day(c.date) && num(c.close));
}

export const dayNumber = (date: string) => Date.parse(`${date}T00:00:00Z`);

/** The drawing window: the last ~2 months of closes up to the last future point, and the price range of everything drawn. */
export function linesFrame(doc: FutureLinesDoc, ids: LineId[], historyCount = 3) {
  const closes = doc.closes.slice(-45);
  const shown: { id: LineId; line: FutureLine; latest: boolean }[] = [];
  for (const id of ids) {
    const latest = doc.lines[id];
    if (latest) shown.push({ id, line: latest, latest: true });
    for (const old of (doc.history[id] || []).filter(h => !latest || h.rec !== latest.rec || h.recordedAt !== latest.recordedAt).slice(-historyCount))
      shown.push({ id, line: old, latest: false });
  }
  const start = closes.length ? dayNumber(closes[0].date) : Math.min(...shown.map(s => dayNumber(s.line.rec)));
  const lastPoint = Math.max(...shown.filter(s => s.latest).flatMap(s => s.line.points.map(p => dayNumber(p.date))), closes.length ? dayNumber(closes.at(-1)!.date) : 0);
  const end = lastPoint + 5 * 86400_000;
  const values = [...closes.map(c => c.close), ...shown.filter(s => s.latest).flatMap(s => s.line.points.map(p => p.price))];
  if (ids.includes('commentator') && doc.wave && !doc.wave.settledBeforeRecord) values.push(doc.wave.target, doc.wave.stop);
  const low = Math.min(...values) * 0.985, high = Math.max(...values) * 1.015;
  const eps = shown.find(s => s.latest && s.line.eps)?.line.eps ?? null;
  const multiples = eps ? Array.from({ length: 40 }, (_, i) => i + 5).filter(m => eps * m >= low && eps * m <= high) : [];
  return { closes, shown, start, end, low, high, eps, multiples };
}

/** The drawn path starts at the recorded close (the close on the record date) and then follows its points. */
export function pathPoints(line: FutureLine, closes: { date: string; close: number }[]) {
  const base = closes.find(c => c.date === line.rec);
  return [...(base ? [{ date: base.date, price: base.close }] : []), ...line.points.map(p => ({ date: p.date, price: p.price }))];
}

/** The first point after the last close: the line's next turning point. */
export function nextTurn(line: FutureLine | null | undefined, after: string): FuturePoint | null {
  return line?.points.find(p => p.date > after) ?? null;
}

/** One-line score on the standard measure, or where it stands before that. */
export function scoreJa(record: LineRecord | undefined): string {
  if (!record || !record.records) return '記録なし';
  const m = record.standard;
  if (!m || !m.n) return '判定前';
  return `当たり ${m.hit}/${m.n}` + (m.randomMean !== null ? `（偶然なら${m.randomMean}）` : '');
}
