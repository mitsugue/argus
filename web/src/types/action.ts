// Action-decision domain types. Every alert, every watchlist row, every
// daily judgment carries one of these labels.

export type ActionKey =
  | 'EXIT'
  | 'TRIM'
  | 'WAIT'
  | 'WAIT_FOR_PULLBACK'
  | 'BUY_DIP'
  | 'ADD'
  | 'HOLD';

// Core (long-term index) portfolio uses its own quieter vocabulary so
// "EXIT" never sits next to a NISA accumulation row.
export type CoreActionKey =
  | 'CONTINUE'
  | 'GRADUAL_ADD'
  | 'DEFER_LUMP_SUM'
  | 'NO_SELL_ACTION';

export type AssetClass =
  | 'JP_STOCK'
  | 'US_STOCK'
  | 'JP_INDEX'
  | 'US_INDEX'
  | 'GOLD'
  | 'REIT'
  | 'BOND'
  | 'CRYPTO'
  | 'COMMODITY'
  | 'USDJPY'
  | 'CASH';

export type Confidence = 'low' | 'med' | 'high';
export type RiskLevel = 'low' | 'med' | 'high' | 'extreme';
