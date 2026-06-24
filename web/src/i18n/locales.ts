// Locale dictionaries (v10.123). Typed keys → no stray hardcoded chrome in
// components for these. Long-tail dynamic content (backend reasoning) carries its
// own en/ja fields and is selected via i18n.pick().

export type Locale = 'en' | 'ja';

const en = {
  // nav
  'nav.today': 'Today',
  'nav.watchlist': 'Watchlist',
  'nav.marketContext': 'Market Context',
  'nav.corePortfolio': 'Core Portfolio',
  'nav.guide': 'Glossary / Guide',
  'nav.todaysCall': "Today's call",
  // page titles
  'page.today': 'Daily Command Center',
  // command card
  'cmd.newEntry': 'NEW ENTRY',
  'cmd.add': 'ADD',
  'cmd.existing': 'EXISTING',
  'cmd.blocked': 'BLOCKED',
  'cmd.allowed': 'ALLOWED',
  'cmd.risk': 'RISK',
  'cmd.data': 'DATA',
  'cmd.whyNow': 'WHY NOW',
  'cmd.nextReview': 'NEXT REVIEW',
  'cmd.viewContext': 'VIEW MARKET CONTEXT',
  'cmd.whatMeans': 'What does this mean?',
  'cmd.confCap': 'Decision confidence is capped at',
  'cmd.disclaimer': 'Action Level = capital-deployment permission, not model confidence and not market regime. Decision-support only — ARGUS never places an order.',
  'cmd.ladderCap': 'CAPITAL DEPLOYMENT PERMISSION',
  'cmd.current': '← CURRENT',
  // market status
  'status.market': 'MARKET STATUS',
  'status.open': 'OPEN',
  'status.closed': 'CLOSED',
  'status.h24': '24H',
  // common
  'common.loading': 'Loading…',
  'common.connecting': 'connecting…',
  'common.detail': 'Detail',
  'common.touchToday': 'Touch today',
  'common.avoidToday': 'Avoid today',
  'common.language': 'Language',
};

type Dict = typeof en;
export type DictKey = keyof Dict;

const ja: Record<DictKey, string> = {
  'nav.today': '今日',
  'nav.watchlist': 'ウォッチリスト',
  'nav.marketContext': '地合い',
  'nav.corePortfolio': '資産配分',
  'nav.guide': '用語 / 使い方',
  'nav.todaysCall': '今日の判断',
  'page.today': '今日の司令室',
  'cmd.newEntry': '新規購入',
  'cmd.add': '買い増し',
  'cmd.existing': '既存ポジション',
  'cmd.blocked': '禁止',
  'cmd.allowed': '可',
  'cmd.risk': 'リスク',
  'cmd.data': 'データ',
  'cmd.whyNow': 'なぜ今',
  'cmd.nextReview': '次の見直し',
  'cmd.viewContext': '地合いを見る',
  'cmd.whatMeans': 'これはどういう意味?',
  'cmd.confCap': '判断の信頼度の上限は',
  'cmd.disclaimer': 'アクションレベル=資本投下の許可であり、モデルの信頼度や地合いとは別物。決定支援のみ・ARGUSは注文を出しません。',
  'cmd.ladderCap': '資本投下の許可レベル',
  'cmd.current': '← 現在',
  'status.market': '市場ステータス',
  'status.open': '取引中',
  'status.closed': '閉場',
  'status.h24': '24時間',
  'common.loading': '読み込み中…',
  'common.connecting': '接続中…',
  'common.detail': '詳細',
  'common.touchToday': '今日触る',
  'common.avoidToday': '今日避ける',
  'common.language': '言語',
};

export const DICT: Record<Locale, Dict> = { en, ja };
