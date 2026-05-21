import type { AlertItem, GlobePillar, TrackedSymbol } from '../types';

let _id = 0;
export const uid = (prefix = 'id') => `${prefix}-${Date.now().toString(36)}-${(_id++).toString(36)}`;

export const INITIAL_PILLARS: GlobePillar[] = [
  // Asia
  { id: 'tk', lat: 35.6895, lng: 139.6917, label: 'TYO', region: 'asia', intensity: 0.85, color: 'cyan', detail: 'Nikkei +1.2% / 銘柄監視 184' },
  { id: 'hk', lat: 22.3193, lng: 114.1694, label: 'HKG', region: 'asia', intensity: 0.55, color: 'cyan', detail: 'HSI +0.4% / Tech rally' },
  { id: 'sg', lat: 1.3521, lng: 103.8198, label: 'SGX', region: 'asia', intensity: 0.4, color: 'cyan', detail: 'STI flat' },
  { id: 'sh', lat: 31.2304, lng: 121.4737, label: 'SHA', region: 'asia', intensity: 0.62, color: 'cyan', detail: 'CSI300 +0.8%' },
  { id: 'kr', lat: 37.5665, lng: 126.978, label: 'SEL', region: 'asia', intensity: 0.45, color: 'cyan', detail: 'KOSPI -0.3%' },
  // Middle East
  { id: 'du', lat: 25.2048, lng: 55.2708, label: 'DXB', region: 'middle-east', intensity: 0.7, color: 'amber', detail: 'Oil futures +2.1%' },
  { id: 'rh', lat: 24.7136, lng: 46.6753, label: 'RYH', region: 'middle-east', intensity: 0.9, color: 'amber', detail: 'Geopolitical signal ▲' },
  { id: 'te', lat: 32.0853, lng: 34.7818, label: 'TLV', region: 'middle-east', intensity: 0.55, color: 'amber', detail: 'TASE volume spike' },
  // US
  { id: 'ny', lat: 40.7128, lng: -74.006, label: 'NYC', region: 'us', intensity: 0.95, color: 'cyan', detail: 'NYSE pre-market hot' },
  { id: 'sf', lat: 37.7749, lng: -122.4194, label: 'SFO', region: 'us', intensity: 0.6, color: 'cyan', detail: 'Tech sector rotation' },
  { id: 'ch', lat: 41.8781, lng: -87.6298, label: 'CHI', region: 'us', intensity: 0.5, color: 'cyan', detail: 'CME futures stable' },
  // Anomaly
  { id: 'mx', lat: 19.4326, lng: -99.1332, label: 'MEX', region: 'us', intensity: 0.4, color: 'danger', detail: 'Currency anomaly ⚠' },
];

const SYMBOL_SEED = [
  { code: 'AAPL', name: 'Apple Inc.', base: 232.4 },
  { code: 'NVDA', name: 'NVIDIA Corp.', base: 142.8 },
  { code: 'TSLA', name: 'Tesla, Inc.', base: 358.1 },
  { code: '7203', name: 'Toyota Motor', base: 2890 },
  { code: '9984', name: 'SoftBank Group', base: 11240 },
];

export function seedSymbols(): TrackedSymbol[] {
  const now = Date.now();
  return SYMBOL_SEED.map((s) => {
    const predicted = +(s.base * (1 + (Math.random() * 0.04 - 0.02))).toFixed(2);
    return {
      code: s.code,
      name: s.name,
      currentPrice: s.base,
      predictedPrice: predicted,
      actualPrice: null,
      predictedAt: now,
      resolvesAt: now + 10 * 60 * 1000,
      history: seedHistory(s.base),
    } satisfies TrackedSymbol;
  });
}

function seedHistory(base: number) {
  const n = 12;
  const out = [];
  for (let i = 0; i < n; i++) {
    const predicted = +(base * (1 + (Math.random() * 0.05 - 0.025))).toFixed(2);
    const actual = +(predicted * (1 + (Math.random() * 0.03 - 0.015))).toFixed(2);
    // hit if direction matches (predicted vs base and actual vs base)
    const dirP = predicted >= base;
    const dirA = actual >= base;
    out.push({
      id: `h-${i}`,
      timestamp: Date.now() - (n - i) * 10 * 60 * 1000,
      predicted,
      actual,
      hit: dirP === dirA,
    });
  }
  return out;
}

const ALERT_TEMPLATES: Array<Omit<AlertItem, 'id' | 'createdAt'>> = [
  { symbol: 'NVDA', title: 'Breakout signal', detail: 'VWAP奪還 + 出来高 3.2x。10分予測 +1.4%。', severity: 'info' },
  { symbol: '9984', title: 'Sentinel: 短期売り浴び', detail: '空売り比率が直近平均の1.8倍。逆張り候補。', severity: 'warn' },
  { symbol: 'AAPL', title: 'Catalyst detected', detail: 'プレマーケット EPS サプライズ報道。', severity: 'info' },
  { symbol: 'TSLA', title: 'Critical: liquidity drain', detail: '板の厚みが急減。撤退ライン到達まで -0.6%。', severity: 'critical' },
  { symbol: '7203', title: 'Theme rotation', detail: 'EV銘柄からハイブリッド回帰の流れ検知。', severity: 'info' },
];

export function randomAlert(): AlertItem {
  const t = ALERT_TEMPLATES[Math.floor(Math.random() * ALERT_TEMPLATES.length)];
  return { ...t, id: uid('alert'), createdAt: Date.now() };
}

export function mutatePillars(pillars: GlobePillar[]): GlobePillar[] {
  return pillars.map((p) => {
    const delta = (Math.random() - 0.5) * 0.15;
    const intensity = Math.max(0.15, Math.min(1, p.intensity + delta));
    return { ...p, intensity };
  });
}

export function tickSymbol(s: TrackedSymbol): TrackedSymbol {
  // Simulate actual price drifting toward (or past) predicted
  const now = Date.now();
  const progress = Math.min(1, (now - s.predictedAt) / (s.resolvesAt - s.predictedAt));
  const target = s.predictedPrice;
  const noise = (Math.random() - 0.5) * (s.currentPrice * 0.004);
  const blended = s.currentPrice + (target - s.currentPrice) * 0.08 + noise;
  const actualPrice = progress >= 1 ? +(target * (1 + (Math.random() * 0.02 - 0.01))).toFixed(2) : null;

  if (progress >= 1) {
    // Resolve & roll forward
    const dirPredicted = s.predictedPrice >= s.currentPrice;
    const dirActual = (actualPrice ?? s.currentPrice) >= s.currentPrice;
    const hit = dirPredicted === dirActual;
    const newCurrent = actualPrice ?? s.currentPrice;
    const newPredicted = +(newCurrent * (1 + (Math.random() * 0.04 - 0.02))).toFixed(2);
    return {
      ...s,
      currentPrice: newCurrent,
      predictedPrice: newPredicted,
      actualPrice: null,
      predictedAt: now,
      resolvesAt: now + 10 * 60 * 1000,
      history: [
        ...s.history.slice(-19),
        { id: uid('h'), timestamp: now, predicted: s.predictedPrice, actual: newCurrent, hit },
      ],
    };
  }

  return { ...s, currentPrice: +blended.toFixed(2), actualPrice };
}

export function hitRate(s: TrackedSymbol): number {
  if (!s.history.length) return 0;
  const hits = s.history.filter((h) => h.hit).length;
  return hits / s.history.length;
}
