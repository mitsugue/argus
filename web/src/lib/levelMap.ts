// Nikkei morning level map (server lane jp_market_level_map, 2026-10-04).
// A map fixed before each open and its pre-registered record; past
// frequencies, never probabilities, never a trading signal.
export type LevelMapRow = {
  side: 'UP' | 'DOWN'; kinds: string[]; price: number; distancePct: number; distanceAtr: number;
  multiple?: number | null; tier: string; bandJa?: string; pastFrequencyPct?: number;
  reachedWithin10SessionsPct?: number; sessionsMedian?: number; sessions25?: number; sessions75?: number;
};
export type LevelMapRecord = {
  schemaVersion: string; morningOf: string; createdAt: string; previousClose: number; previousSession: string;
  atr14: number; eps: number; epsDate: string; per: number; epsJumped: boolean; epsLabelJa: string;
  epsCoverage?: { members?: number; filledFromTrailing?: number; negativeForecast?: number; missingEarnings?: number } | null;
  constituentsAsOf?: string | null; rows: LevelMapRow[]; atrGuides: { UP: number[]; DOWN: number[] };
  fixedNotesJa: string[]; actionAuthority: false;
};
export type LevelMapTally = { STOPPED: number; BROKE: number; UNDECIDED: number; OPEN: number };
export type LevelMapScore = {
  firstMorning: string | null; mornings: number; phases: number; phaseOutcomes: LevelMapTally;
  fakeLineOutcomes: LevelMapTally; preRegisteredOnly: boolean;
  turningPoints: { evaluated: number; perLineHits: number; atr2Hits: number; chanceExpected: number };
};
export type LevelMapState = {
  schemaVersion: 'jp-market-level-map-state-v1'; status: string; latest: LevelMapRecord | null;
  morningCount: number; missedMornings: string[]; score: LevelMapScore | null; retrospective: LevelMapScore | null;
  actionAuthority: false;
};

const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

export function validLevelMap(value: unknown): value is LevelMapState {
  const v = value as LevelMapState | null;
  if (!v || typeof v !== 'object' || v.schemaVersion !== 'jp-market-level-map-state-v1' || v.actionAuthority !== false
    || !Array.isArray(v.missedMornings)) return false;
  const latest = v.latest;
  if (latest == null) return true;
  return latest.actionAuthority === false && typeof latest.morningOf === 'string' && num(latest.previousClose)
    && num(latest.atr14) && num(latest.eps) && Array.isArray(latest.rows)
    && latest.rows.every(r => (r.side === 'UP' || r.side === 'DOWN') && num(r.price) && num(r.distancePct)
      && num(r.distanceAtr) && Array.isArray(r.kinds))
    && Array.isArray(latest.atrGuides?.UP) && Array.isArray(latest.atrGuides?.DOWN) && Array.isArray(latest.fixedNotesJa);
}

const multipleText = (m?: number | null) => m == null ? '' : Number.isInteger(m) ? `${m}` : m.toFixed(3);

/** What a row is, in the product's words (never "止まる", never a probability). */
export function rowLabelJa(row: LevelMapRow): string {
  return row.kinds.map(kind => kind === 'PER_LINE' ? `PER${multipleText(row.multiple)}倍線（毎朝動く）`
    : kind === 'SAME_MULTIPLE' ? `直前の${row.side === 'UP' ? '天井' : '底'}と同じ倍率 ${multipleText(row.multiple)}倍`
    : kind === 'PIVOT_PRICE' ? `直前の${row.side === 'UP' ? '天井' : '底'}の価格（参考）` : '距離の目安').join(' / ');
}

export function evidenceJa(row: LevelMapRow): string {
  if (row.kinds.includes('SAME_MULTIPLE') && !row.kinds.includes('PER_LINE')) return '保留・弱い';
  if (row.kinds.includes('PER_LINE')) return '保留（2010〜2023年は偶然並み）';
  return '参考';
}
