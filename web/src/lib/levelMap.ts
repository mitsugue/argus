// Nikkei morning level map (server lane jp_market_level_map, 2026-10-04).
// A map fixed before each open and its pre-registered record; past
// frequencies, never probabilities, never a trading signal.
export type LevelMapRow = {
  side: 'UP' | 'DOWN'; kinds: string[]; price: number; distancePct: number; distanceAtr: number;
  multiple?: number | null; mergedMultiples?: number[]; tier: string; bandJa?: string; pastFrequencyPct?: number;
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
export type ValuationHistory = {
  basis: 'ARGUS_ESTIMATE_MARKET_CAP_WEIGHTED_FORWARD'; firstDate: string; lastDate: string;
  count: number; missingSessions: number; sufficient: boolean; median: number; minimum: number; maximum: number;
  upperMultiple: number; atOrAboveUpper: number; retrospective: true; actionAuthority: false;
};
export function validValuationHistory(value: unknown): value is ValuationHistory {
  const v = value as ValuationHistory | null;
  return !!v && v.basis === 'ARGUS_ESTIMATE_MARKET_CAP_WEIGHTED_FORWARD' && v.retrospective === true
    && v.actionAuthority === false && /^\d{4}-\d{2}-\d{2}$/.test(v.firstDate) && /^\d{4}-\d{2}-\d{2}$/.test(v.lastDate)
    && v.firstDate <= v.lastDate && Number.isInteger(v.count) && v.count > 0
    && Number.isInteger(v.missingSessions) && v.missingSessions >= 0 && typeof v.sufficient === 'boolean'
    && [v.median, v.minimum, v.maximum, v.upperMultiple].every(n => Number.isFinite(n) && n > 0)
    && v.minimum <= v.median && v.median <= v.maximum && Number.isInteger(v.atOrAboveUpper)
    && v.atOrAboveUpper >= 0 && v.atOrAboveUpper <= v.count;
}
export type LevelMapState = {
  schemaVersion: 'jp-market-level-map-state-v1'; status: string; latest: LevelMapRecord | null;
  chart?: { nearest?: unknown; today?: string; closePending?: boolean; valuationHistory?: unknown; displayMap?: LevelMapRecord & { displayOnly: true; asOf: string; valuationPending: boolean } };
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
  const multiples = Array.isArray(row.mergedMultiples) ? row.mergedMultiples.filter(num) : [row.multiple];
  const per = multiples.find(m => Number.isInteger(m)) ?? row.multiple;
  const same = multiples.find(m => m != null && !Number.isInteger(m)) ?? row.multiple;
  return row.kinds.map(kind => kind === 'PER_LINE' ? `${row.kinds.length > 1 ? '近接する' : ''}PER${multipleText(per)}倍線（EPS更新で動く）`
    : kind === 'SAME_MULTIPLE' ? `直前の${row.side === 'UP' ? '天井' : '底'}と同じ倍率 ${multipleText(same)}倍`
    : kind === 'PIVOT_PRICE' ? `直前の${row.side === 'UP' ? '天井' : '底'}の価格（参考）` : '距離の目安').join(' / ');
}

export function evidenceJa(row: LevelMapRow): string {
  if (row.kinds.includes('SAME_MULTIPLE') && !row.kinds.includes('PER_LINE')) return '山・谷の予測力は未確認';
  if (row.kinds.includes('PER_LINE')) return '山・谷の予測力は偶然並み（2010〜2023年）';
  return '参考';
}

export function currentLevelMap(state: LevelMapState): LevelMapRecord | null {
  const shown = state.chart?.displayMap;
  if (!shown) return state.latest;
  const valid = shown.displayOnly === true && typeof shown.valuationPending === 'boolean'
    && /^\d{4}-\d{2}-\d{2}$/.test(shown.asOf) && shown.asOf === shown.previousSession
    && typeof shown.epsDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(shown.epsDate)
    && shown.epsDate <= shown.asOf && shown.morningOf > shown.asOf
    && [shown.previousClose, shown.eps, shown.atr14, shown.per].every(n => num(n) && n > 0)
    && validLevelMap({ ...state, latest: shown });
  return valid ? shown : state.latest;
}

/** Integer PER prices stay exact even when the detailed map merges nearby pivots.
 * Stats are admitted only for this price and distance, never from a nearby row.
 * Older replies without nearest distances can use a matching unmerged map row.
 */
export function nearestPerRows(map: LevelMapRecord, nearest: unknown): LevelMapRow[] {
  if (![map.eps, map.previousClose, map.atr14].every(v => num(v) && v > 0)) return [];
  const ratio = map.previousClose / map.eps;
  return (['UP', 'DOWN'] as const).map(side => {
    const multiple = side === 'UP' ? Math.floor(ratio) + 1 : Math.ceil(ratio) - 1;
    const price = Math.round(map.eps * multiple * 100) / 100;
    const distancePct = (price / map.previousClose - 1) * 100;
    const distanceAtr = (price - map.previousClose) / map.atr14;
    const matches = (value: unknown): value is LevelMapRow => {
      const r = value as LevelMapRow | null;
      return !!r && r.side === side && r.multiple === multiple && num(r.price) && Math.abs(r.price - price) <= .5
        && num(r.distancePct) && Math.abs(r.distancePct - distancePct) <= .002
        && num(r.distanceAtr) && Math.abs(r.distanceAtr - distanceAtr) <= .002
        && num(r.reachedWithin10SessionsPct) && r.reachedWithin10SessionsPct >= 0 && r.reachedWithin10SessionsPct <= 100
        && num(r.sessionsMedian) && r.sessionsMedian >= 0;
    };
    const stats = (Array.isArray(nearest) ? nearest.find(matches) : undefined)
      ?? map.rows.find(r => r.kinds.includes('PER_LINE') && matches(r));
    return { ...stats, side, multiple, price, distancePct, distanceAtr, kinds: ['PER_LINE'], tier: 'MAP' };
  }).filter(row => row.multiple > 0);
}
