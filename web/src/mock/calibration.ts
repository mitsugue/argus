import type {
  CalibrationBin,
  CalibrationStats,
  Direction,
  Horizon,
  PredictionEntry,
} from '../types/calibration';
import { uid } from './data';

const DAY_MS = 24 * 60 * 60 * 1000;
const SYMBOLS = ['AAPL', 'NVDA', 'TSLA', 'MSFT', '7203', '9984', 'AMD', 'META', '6758', 'AMZN'];

// Mock ledger spans the last 30 days. Hit rate trends upward over time —
// the "model is improving" story the user wants visible.
export function generateMockLedger(now: number = Date.now()): PredictionEntry[] {
  const entries: PredictionEntry[] = [];
  // 5 predictions per day for 30 days = 150
  for (let day = 30; day >= 0; day--) {
    const ts = now - day * DAY_MS - Math.random() * DAY_MS;
    // Hit rate climbs: day 30 → ~52%, day 0 → ~78%
    const expectedHit = 0.52 + (30 - day) / 30 * 0.26;
    const picksToday = day === 0 ? 3 : 5;
    for (let i = 0; i < picksToday; i++) {
      const code = SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)];
      const direction: Direction = Math.random() > 0.5 ? 'up' : 'down';
      // Probability close to expectedHit + noise — keeps the model honest
      const probability = clamp(expectedHit + (Math.random() - 0.5) * 0.18, 0.45, 0.92);
      const price = 80 + Math.random() * 320;
      const horizon: Horizon = day === 0 && i === picksToday - 1 ? '1d' : pickHorizon();
      const resolvesAt = ts + horizonMs(horizon);
      const pending = resolvesAt > now;
      const isHit = !pending && Math.random() < probability;
      const movePct = pending
        ? null
        : (direction === 'up' ? 1 : -1) *
          (isHit ? 0.5 + Math.random() * 2.5 : -(0.2 + Math.random() * 1.8));
      const priceAtResolution = pending ? null : +(price * (1 + (movePct ?? 0) / 100)).toFixed(2);
      entries.push({
        id: uid('pred'),
        predictedAt: ts,
        resolvesAt,
        resolvedAt: pending ? null : resolvesAt,
        code,
        direction,
        probability: +probability.toFixed(3),
        horizon,
        priceAtPrediction: +price.toFixed(2),
        priceAtResolution,
        movePct: movePct == null ? null : +movePct.toFixed(2),
        outcome: pending ? 'pending' : isHit ? 'hit' : 'miss',
        reasonCode: REASONS[Math.floor(Math.random() * REASONS.length)],
      });
    }
  }
  // Newest first
  return entries.sort((a, b) => b.predictedAt - a.predictedAt);
}

const REASONS = [
  'VWAP_RECLAIM',
  'CATALYST_NEWS',
  'EDINET_FILING',
  'SHORT_SQUEEZE',
  'VOL_BREAKOUT',
  'SECTOR_ROTATION',
  'LLM_CONSENSUS',
];

function pickHorizon(): Horizon {
  const r = Math.random();
  if (r < 0.55) return '10m';
  if (r < 0.85) return '1h';
  return '1d';
}

function horizonMs(h: Horizon): number {
  switch (h) {
    case '10m': return 10 * 60 * 1000;
    case '1h':  return 60 * 60 * 1000;
    case '1d':  return DAY_MS;
    case 'open': return 6 * 60 * 60 * 1000;
  }
}

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

export function computeStats(
  entries: PredictionEntry[],
  windowDays = 30,
  now: number = Date.now(),
): CalibrationStats {
  const cutoff = now - windowDays * DAY_MS;
  const inWindow = entries.filter((e) => e.predictedAt >= cutoff);
  const resolved = inWindow.filter((e) => e.outcome !== 'pending');
  const pending = inWindow.filter((e) => e.outcome === 'pending');
  const hits = resolved.filter((e) => e.outcome === 'hit').length;
  const hitRate = resolved.length ? hits / resolved.length : 0;
  const expectedRate = resolved.length
    ? resolved.reduce((s, e) => s + e.probability, 0) / resolved.length
    : 0;
  const brierScore = resolved.length
    ? resolved.reduce((s, e) => {
        const actual = e.outcome === 'hit' ? 1 : 0;
        return s + (e.probability - actual) ** 2;
      }, 0) / resolved.length
    : 0;

  // Daily hit rate sparkline
  const dailyHitRate: CalibrationStats['dailyHitRate'] = [];
  for (let day = windowDays - 1; day >= 0; day--) {
    const dayStart = now - (day + 1) * DAY_MS;
    const dayEnd = now - day * DAY_MS;
    const dayEntries = resolved.filter(
      (e) => e.predictedAt >= dayStart && e.predictedAt < dayEnd,
    );
    const dayHits = dayEntries.filter((e) => e.outcome === 'hit').length;
    dailyHitRate.push({
      day: new Date(dayStart).toISOString().slice(5, 10),
      rate: dayEntries.length ? dayHits / dayEntries.length : 0,
      n: dayEntries.length,
    });
  }

  // Calibration bins (5 buckets)
  const bins: CalibrationBin[] = [];
  const numBins = 5;
  for (let b = 0; b < numBins; b++) {
    const lo = b / numBins;
    const hi = (b + 1) / numBins;
    const bucket = resolved.filter((e) => e.probability >= lo && e.probability < hi + (b === numBins - 1 ? 0.001 : 0));
    const bucketHits = bucket.filter((e) => e.outcome === 'hit').length;
    bins.push({
      predictedProb: (lo + hi) / 2,
      count: bucket.length,
      actualRate: bucket.length ? bucketHits / bucket.length : 0,
    });
  }

  return {
    windowDays,
    resolvedCount: resolved.length,
    pendingCount: pending.length,
    hitCount: hits,
    hitRate,
    expectedRate,
    brierScore,
    dailyHitRate,
    bins,
  };
}
