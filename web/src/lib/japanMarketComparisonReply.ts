import type { JapanMarketComparison } from '../types/japanMarketComparison';
import { validJapanMarketComparison } from './japanMarketComparison';
import { validLevelMap, type LevelMapState } from './levelMap';
import { validResearchChart } from './researchChart';

export type ComparisonReply = { document: JapanMarketComparison | null; reason: string | null;
  lastSuccessfulAcquisitionAt: string | null; levelMap?: LevelMapState | null };

/** The close/PER display is independent of the slower analog calculation. */
export function comparisonReply(value: unknown, horizon: number): ComparisonReply {
  const body = value as Record<string, unknown> | null;
  if (!body || body.actionAuthority !== false || body.automaticAiCalls !== 0) throw new Error('invalid_comparison_response');
  const unavailable = body.status === 'unavailable' && body.comparison === null;
  if (!unavailable && body.status !== 'available') throw new Error('invalid_comparison_response');
  const document = !unavailable && validJapanMarketComparison(body.comparison, horizon) ? body.comparison : null;
  const levelMap = validLevelMap(body.levelMap) && validResearchChart(body.levelMap.chart) ? body.levelMap : null;
  if (!unavailable && !document && !levelMap) throw new Error('invalid_comparison_response');
  return { document,
    reason: unavailable ? typeof body.reason === 'string' ? body.reason : 'unavailable'
      : document ? null : 'invalid_comparison_response',
    lastSuccessfulAcquisitionAt: typeof body.lastSuccessfulAcquisitionAt === 'string'
      && Number.isFinite(Date.parse(body.lastSuccessfulAcquisitionAt)) ? body.lastSuccessfulAcquisitionAt : null,
    levelMap };
}

export function retainComparisonReply(fresh: ComparisonReply, cached?: ComparisonReply): ComparisonReply {
  return { ...fresh, document: fresh.document ?? cached?.document ?? null,
    levelMap: fresh.levelMap ?? cached?.levelMap ?? null,
    lastSuccessfulAcquisitionAt: fresh.lastSuccessfulAcquisitionAt ?? cached?.lastSuccessfulAcquisitionAt ?? null };
}

/** Only reread the cached display more often around an unfinished close. */
export function comparisonReadInterval(reply: ComparisonReply | undefined, nowMillis: number): number {
  const jst = new Date(nowMillis + 9 * 60 * 60_000);
  const minute = jst.getUTCHours() * 60 + jst.getUTCMinutes();
  if (jst.getUTCDay() === 0 || jst.getUTCDay() === 6 || minute >= 22 * 60) return 600_000;
  // A ten-minute timer started before the close must end at the boundary.
  if (minute < 15 * 60 + 30) {
    const close = Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate(), 15, 30);
    return Math.min(600_000, close - jst.getTime());
  }
  const chart = reply?.levelMap?.chart as { closePending?: boolean; displayMap?: { valuationPending?: boolean } } | undefined;
  return minute < 15 * 60 + 46 || chart?.closePending || chart?.displayMap?.valuationPending ? 60_000 : 600_000;
}
