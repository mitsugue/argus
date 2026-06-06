import type {
  AssetActionCard,
  CorePosition,
  DailyJudgment,
  MarketEvent,
} from '../types/dashboard';

// Mock content. Display text (summary, reasons, news, regime notes) is
// rendered in Japanese — the user prefers JP for information until they
// settle in. UI chrome (labels, action keys, section titles) stays
// English so the design system remains consistent.

// Top reasons are interpretive — they say WHY today's posture is what it
// is, not just "CPI in 24h" (the header chip already says that).
export const todayJudgment: DailyJudgment = {
  date: '2026-06-09',
  overall: 'WAIT',
  risk: 'high',
  regime: ['Event Risk', 'Rates Pressure'],
  summary:
    'マクロイベントウィンドウが活発。確信度は通常より低い。発表後の確認まで新規エントリーを抑制。',
  reasons: [
    'マクロイベントウィンドウが活発で、確信度が通常より低い。',
    '金利上昇が長期デュレーション資産を圧迫している。',
    'ハイベータ銘柄でオーバーナイトのモメンタムが弱い。',
  ],
  assetsToTouch: ['金(ヘッジ)', '現金比率', '日本大型ディフェンシブ'],
  assetsToAvoid: ['米グロース株', 'ハイベータ暗号資産', '長期国債'],
  nextCondition:
    'CPI 通過 → イールド反応を確認 → BUY DIP 候補を再評価。',
  updatedAt: Date.now(),
};

export const actionAlerts: AssetActionCard[] = [
  {
    assetClass: 'JP_STOCK',
    displayName: 'Japan Individual Stocks',
    action: 'WAIT',
    confidence: 'med',
    risk: 'med',
    reason: 'TSE の値幅は横ばい。主要テーマは米CPI を控え様子見。',
    dataPoints: [
      'TOPIX adv/dec ratio: 1.02',
      '海外勢ネットフロー: -¥48bn (5d)',
      '信用買い比率: 3.4(高水準)',
    ],
    nextCondition: '米CPI 通過後 → 朝の値動き銘柄を再スクリーン。',
  },
  {
    assetClass: 'US_STOCK',
    displayName: 'US Individual Stocks',
    action: 'WAIT_FOR_PULLBACK',
    confidence: 'high',
    risk: 'high',
    reason: 'Mag-7 は買われすぎ、値幅は薄い。秩序ある押し目を待つ。',
    dataPoints: [
      'SPX RSI(14): 71',
      '50DMA 超え銘柄: 58%',
      'VIX: 17.4(上昇中)',
    ],
    nextCondition: 'SPX 日中 -2% または VIX > 22 → 再評価。',
  },
  {
    assetClass: 'GOLD',
    displayName: 'Gold',
    action: 'HOLD',
    confidence: 'high',
    risk: 'low',
    reason: 'イベントヘッジとして保持。モメンタムは正だが伸び切り感あり。',
    dataPoints: [
      'XAU/USD: 2,348(+0.4% 5d)',
      '実質利回り: 1.8%(レンジ)',
      'GLD ネット流入: +$220m(5d)',
    ],
    nextCondition: 'CPI 上振れ → 部分利確。',
  },
  {
    assetClass: 'REIT',
    displayName: 'REITs',
    action: 'WAIT',
    confidence: 'med',
    risk: 'med',
    reason: '金利感応度が高い。デュレーションリスクが落ち着くまで見送り。',
    dataPoints: ['VNQ -1.1%(5d)', '米10Y: 4.42%'],
    nextCondition: '米10Y が 4.30% を割る → 再評価。',
  },
  {
    assetClass: 'BOND',
    displayName: 'Bonds',
    action: 'WAIT_FOR_PULLBACK',
    confidence: 'high',
    risk: 'med',
    reason: '利回り上昇中。カーブが安定するまでデュレーションは増やさない。',
    dataPoints: [
      'TLT -1.8%(5d)',
      '米10Y: 4.42%(+12 bps 5d)',
      '2s10s: -32 bps',
    ],
    nextCondition: '10Y がピークアウト → 段階買い開始。',
  },
  {
    assetClass: 'CRYPTO',
    displayName: 'Crypto',
    action: 'TRIM',
    confidence: 'med',
    risk: 'high',
    reason: 'BTC/ETH はイベントリスクに対し伸び切り。一部利確で確保。',
    dataPoints: [
      'BTC: $68,200(+9% 7d)',
      'ETH: $3,820(+11% 7d)',
      'ファンディング: 0.04%(高水準)',
    ],
    nextCondition: 'ファンディング > 0.06% または BTC > $71k → さらに利確。',
  },
  {
    assetClass: 'COMMODITY',
    displayName: 'Commodities',
    action: 'WAIT',
    confidence: 'low',
    risk: 'med',
    reason: '原油・基礎金属でシグナル混在。明確なエッジなし。',
    dataPoints: ['WTI: $76.2', '銅: $4.18'],
    nextCondition: 'OPEC ヘッドラインまたは中国 PMI のサプライズ。',
  },
  {
    assetClass: 'USDJPY',
    displayName: 'USD/JPY',
    action: 'WAIT',
    confidence: 'high',
    risk: 'med',
    reason: '157 円付近でレンジ。介入リスクが上値を抑える。',
    dataPoints: [
      'USD/JPY: 157.2',
      '財務省レトリック: 強含み',
      '1M インプライド: 8.4%',
    ],
    nextCondition: '158.5 突破または BOJ コメント → 再評価。',
  },
];

export const indexFundStatus: CorePosition[] = [
  {
    symbol: 'eMAXIS Slim S&P 500',
    name: 'eMAXIS Slim S&P 500',
    market: 'JP',
    action: 'CONTINUE',
    reason: '積立は予定通り。バリュエーションは割高だがトレンドは継続。',
  },
  {
    symbol: 'eMAXIS Slim All-Country',
    name: 'eMAXIS Slim 全世界株式(オルカン)',
    market: 'JP',
    action: 'CONTINUE',
    reason: 'NISA 積立を予定通り継続。',
  },
  {
    symbol: 'VTI',
    name: 'Vanguard Total Stock Market ETF',
    market: 'US',
    action: 'DEFER_LUMP_SUM',
    reason: '追加一括は CPI 後の値直しまで保留。',
  },
  {
    symbol: 'Nikkei 225 Index',
    name: '日経 225 連動型',
    market: 'JP',
    action: 'GRADUAL_ADD',
    reason: 'TOPIX 押し目で段階エントリー。3 週間で追加。',
  },
];

const day = 86_400_000;
const t0 = Date.now();

export const upcomingEvents: MarketEvent[] = [
  {
    id: 'cpi-jun',
    kind: 'CPI',
    title: '米CPI(5月)',
    at: t0 + 1 * day,
    impact: 'high',
    note: '総合 3.4% YoY 予想。今週最大のリスク。',
  },
  {
    id: 'fomc-jun',
    kind: 'FOMC',
    title: 'FOMC 政策決定',
    at: t0 + 2 * day,
    impact: 'extreme',
    note: '金利据え置き予想。ドットプロットと SEP が変数。',
  },
  {
    id: 'pce-jun',
    kind: 'PCE',
    title: '米PCE(5月)',
    at: t0 + 22 * day,
    impact: 'high',
  },
  {
    id: 'boj-jul',
    kind: 'BOJ',
    title: '日銀 政策決定会合',
    at: t0 + 30 * day,
    impact: 'high',
    note: 'JGB テーパー速度と為替ガイダンスに注目。',
  },
  {
    id: 'nflx-q',
    kind: 'EARNINGS',
    title: 'NFLX 決算',
    at: t0 + 12 * day,
    impact: 'med',
  },
];
