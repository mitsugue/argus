// Action-decision domain types. The whole new app speaks this vocabulary —
// every alert, every watchlist row, every daily judgment carries an ActionKey.

export type ActionKey =
  | 'ESCAPE'
  | 'TAKE_PARTIAL_PROFIT'
  | 'WAIT'
  | 'PULL_BACK'
  | 'BUY_THE_DIP'
  | 'ADD'
  | 'DO_NOTHING';

// Core (= long-term index) portfolio uses its own vocabulary so that
// "ESCAPE / 逃げる" never appears next to NISA積立 — different mental mode.
export type CoreActionKey =
  | 'ACCUMULATE_CONTINUE'
  | 'WAIT_LUMP_SUM'
  | 'ADD_GRADUALLY'
  | 'NO_SELL_NEEDED';

export type AssetClass =
  | 'JP_STOCK'
  | 'US_STOCK'
  | 'JP_INDEX'
  | 'US_INDEX'
  | 'GOLD'
  | 'REIT'
  | 'BOND'
  | 'CRYPTO'
  | 'USDJPY';

export type Confidence = 'low' | 'med' | 'high';
export type RiskLevel = 'low' | 'med' | 'high' | 'extreme';
