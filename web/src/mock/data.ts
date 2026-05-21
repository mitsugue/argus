import type { AlertItem, GlobePillar, TrackedSymbol } from '../types';

let _id = 0;
export const uid = (prefix = 'id') => `${prefix}-${Date.now().toString(36)}-${(_id++).toString(36)}`;

export const INITIAL_PILLARS: GlobePillar[] = [
  // Asia
  { id: 'tk', lat: 35.6895, lng: 139.6917, label: 'TYO', region: 'asia', intensity: 0.85, color: 'cyan', country: 'Japan', countryCode: 'JP', source: '日経', headline: 'Nikkei +1.2% / 銘柄監視 184' },
  { id: 'hk', lat: 22.3193, lng: 114.1694, label: 'HKG', region: 'asia', intensity: 0.55, color: 'cyan', country: 'Hong Kong', countryCode: 'HK', source: 'SCMP', headline: 'HSI +0.4% / Tech rally' },
  { id: 'sg', lat: 1.3521, lng: 103.8198, label: 'SGX', region: 'asia', intensity: 0.4, color: 'cyan', country: 'Singapore', countryCode: 'SG', source: 'Straits Times', headline: 'STI flat / 商品先物観望' },
  { id: 'sh', lat: 31.2304, lng: 121.4737, label: 'SHA', region: 'asia', intensity: 0.62, color: 'cyan', country: 'China', countryCode: 'CN', source: '財新', headline: 'CSI300 +0.8% / EV補助金延長報道' },
  { id: 'kr', lat: 37.5665, lng: 126.978, label: 'SEL', region: 'asia', intensity: 0.45, color: 'cyan', country: 'South Korea', countryCode: 'KR', source: '中央日報', headline: 'KOSPI -0.3% / Samsung調整' },
  // Middle East
  { id: 'du', lat: 25.2048, lng: 55.2708, label: 'DXB', region: 'middle-east', intensity: 0.7, color: 'amber', country: 'UAE', countryCode: 'AE', source: 'Gulf News', headline: 'Oil futures +2.1% / OPEC+会合控え' },
  { id: 'rh', lat: 24.7136, lng: 46.6753, label: 'RYH', region: 'middle-east', intensity: 0.9, color: 'amber', country: 'Saudi Arabia', countryCode: 'SA', source: 'Al Arabiya', headline: 'Geopolitical signal ▲ / 増産凍結観測' },
  { id: 'te', lat: 32.0853, lng: 34.7818, label: 'TLV', region: 'middle-east', intensity: 0.55, color: 'amber', country: 'Israel', countryCode: 'IL', source: 'Haaretz', headline: 'TASE 出来高 spike / 防衛セクター' },
  // US
  { id: 'ny', lat: 40.7128, lng: -74.006, label: 'NYC', region: 'us', intensity: 0.95, color: 'cyan', country: 'United States', countryCode: 'US', source: 'Bloomberg', headline: 'NYSE pre-market hot / NVDA +3.2%' },
  { id: 'sf', lat: 37.7749, lng: -122.4194, label: 'SFO', region: 'us', intensity: 0.6, color: 'cyan', country: 'United States', countryCode: 'US', source: 'TechCrunch', headline: 'Tech sector rotation / AIインフラ' },
  { id: 'ch', lat: 41.8781, lng: -87.6298, label: 'CHI', region: 'us', intensity: 0.5, color: 'cyan', country: 'United States', countryCode: 'US', source: 'WSJ', headline: 'CME futures stable / 穀物上昇' },
  // Anomaly
  { id: 'mx', lat: 19.4326, lng: -99.1332, label: 'MEX', region: 'us', intensity: 0.4, color: 'danger', country: 'Mexico', countryCode: 'MX', source: 'Reforma', headline: 'Currency anomaly ⚠ / ペソ急変動' },
  // Europe additions for visual balance
  { id: 'ldn', lat: 51.5074, lng: -0.1278, label: 'LDN', region: 'europe', intensity: 0.7, color: 'cyan', country: 'United Kingdom', countryCode: 'GB', source: 'Financial Times', headline: 'FTSE +0.5% / BoE声明待ち' },
  { id: 'fra', lat: 50.1109, lng: 8.6821, label: 'FRA', region: 'europe', intensity: 0.6, color: 'cyan', country: 'Germany', countryCode: 'DE', source: 'Handelsblatt', headline: 'DAX 反発 / 製造業PMI改善' },
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

// Per-pillar rotating headline pool — keeps news stream feeling fresh
export const HEADLINE_POOL: Record<string, string[]> = {
  tk: [
    'Nikkei +1.2% / 銘柄監視 184',
    'TOPIX 反発 / 内需株主導',
    '東証出来高 1.4兆円 / 1月以来',
    '円相場 153円台 / 介入観測再燃',
    '半導体株 急騰 / Rapidus 報道',
  ],
  hk: [
    'HSI +0.4% / Tech rally',
    'Tencent 出来高急増',
    '香港IPO 解禁観測',
    'ハンセン指数 反発',
  ],
  sg: [
    'STI flat / 商品先物観望',
    'シンガポール GDP 上方修正',
    'DBS +2.1% / 金利期待',
  ],
  sh: [
    'CSI300 +0.8% / EV補助金延長報道',
    '上海総合 反発 / 半導体主導',
    '人民銀行 流動性供給',
  ],
  kr: [
    'KOSPI -0.3% / Samsung調整',
    'SK Hynix HBM 増産報道',
    'ウォン安 1380台',
  ],
  du: [
    'Oil futures +2.1% / OPEC+会合控え',
    'Dubai 不動産 取引高 過去最高',
    'WTI 80ドル接近',
  ],
  rh: [
    'Geopolitical signal ▲ / 増産凍結観測',
    'サウジ ARAMCO 出荷量調整',
    '中東情勢 緊張高まる',
    '原油 急騰 / 中東リスクオフ',
  ],
  te: [
    'TASE 出来高 spike / 防衛セクター',
    'Israel tech IPO 観測',
    'シェケル 急変動',
  ],
  ny: [
    'NYSE pre-market hot / NVDA +3.2%',
    'S&P 500 新高値更新',
    'Treasury yields ▲ 4.31%',
    'FOMC minutes / hawkish bias',
    'NYSE 出来高 急増 / AI銘柄',
  ],
  sf: [
    'Tech sector rotation / AIインフラ',
    'TSMC ADR +2.8% / 受注報道',
    'Apple サプライヤー 急騰',
  ],
  ch: [
    'CME futures stable / 穀物上昇',
    'シカゴ小麦 +3% / 天候要因',
    'CME VIX futures 出来高 急増',
  ],
  mx: [
    'Currency anomaly ⚠ / ペソ急変動',
    'メキシコ中銀 想定外利下げ',
    'USMCA 関連 報道',
  ],
  ldn: [
    'FTSE +0.5% / BoE声明待ち',
    'GBP/USD 急騰 / 1.28突破',
    'ロンドン株 銀行株主導',
  ],
  fra: [
    'DAX 反発 / 製造業PMI改善',
    'Siemens 受注 過去最高',
    'ユーロ圏 CPI 速報',
  ],
};

export function pickHeadline(pillarId: string, fallback: string): string {
  const pool = HEADLINE_POOL[pillarId];
  if (!pool || pool.length === 0) return fallback;
  return pool[Math.floor(Math.random() * pool.length)];
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
