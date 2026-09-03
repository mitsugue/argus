// v13.5.38 — MARKET SIGNALS (SIG-01..07) owner-facing view.
//
// The backend projects the seven evidence families into `marketSignals`
// inside the SHO market view (argus_market_signals.py). This module renders
// that projection; when an older backend omits it, the same counting rule is
// derived from the families so the surface never disappears and never lies:
// ACTIVE counts, everything else is shown as its own truthful state.
import { MARKET_SIGNAL_STATE_GLOSSARY } from './glossary';

export type MarketSignalState =
  | 'ACTIVE' | 'CLEAR' | 'DATA_GATED' | 'STALE' | 'LICENSE_BLOCKED' | 'UNAVAILABLE';

export interface MarketSignalRow {
  id: string;
  family: string;
  nameEn: string;
  nameJa: string;
  state: MarketSignalState;
  status?: string | null;
  conditionMet?: boolean | null;
}

export interface MarketSignalsProjection {
  schemaVersion?: string;
  total?: number;
  activeCount?: number;
  countLabel?: string;
  countRule?: string;
  signals?: Array<{
    id?: string; family?: string; nameEn?: string; nameJa?: string;
    state?: string; status?: string | null; conditionMet?: boolean | null;
  }>;
}

export interface MarketSignalsView {
  label: 'MARKET SIGNALS';
  total: number;
  activeCount: number;
  countLabel: string;
  source: 'server' | 'derived';
  signals: Array<MarketSignalRow & { stateJa: string; glossaryKey: string }>;
}

export const MARKET_SIGNAL_DEFINITIONS: ReadonlyArray<{
  id: string; family: string; nameEn: string; nameJa: string;
}> = [
  { id: 'SIG-01', family: 'D01', nameEn: 'Margin / Credit Balance', nameJa: '信用残' },
  { id: 'SIG-02', family: 'D02', nameEn: '1570 / Supply-Demand', nameJa: '1570倍率・需給' },
  { id: 'SIG-03', family: 'D03', nameEn: 'Relative Strength', nameJa: '相対力' },
  { id: 'SIG-04', family: 'D04', nameEn: 'Japan Earnings / Valuation', nameJa: 'EPS基準・バリュエーション' },
  { id: 'SIG-05', family: 'D05', nameEn: 'Foreign Investor Flow', nameJa: '海外フロー' },
  { id: 'SIG-06', family: 'D06', nameEn: 'VIX / MACD', nameJa: 'VIX・MACD' },
  { id: 'SIG-07', family: 'D07', nameEn: 'Earnings Reaction', nameJa: '決算反応' },
];

export const MARKET_SIGNAL_STATE_JA: Record<MarketSignalState, string> = {
  ACTIVE: '点灯', CLEAR: '消灯', DATA_GATED: '判定不能', STALE: '古い',
  LICENSE_BLOCKED: '要ライセンス', UNAVAILABLE: '欠測',
};

const STATES: ReadonlySet<string> = new Set(
  ['ACTIVE', 'CLEAR', 'DATA_GATED', 'STALE', 'LICENSE_BLOCKED', 'UNAVAILABLE']);

/** The single counting rule (mirrors argus_market_signals.signal_state). */
export function signalStateFromFamily(
  row: { status?: string | null; conditionMet?: boolean | null } | null | undefined,
): MarketSignalState {
  if (!row || typeof row !== 'object') return 'UNAVAILABLE';
  if (row.status === 'AVAILABLE') {
    if (row.conditionMet === true) return 'ACTIVE';
    if (row.conditionMet === false) return 'CLEAR';
    return 'DATA_GATED';
  }
  if (row.status === 'STALE') return 'STALE';
  if (row.status === 'LICENSE_BLOCKED') return 'LICENSE_BLOCKED';
  if (row.status === 'PARTIAL' || row.status === 'UNVALIDATED' || row.status === 'DATA_GATED') {
    return 'DATA_GATED';
  }
  return 'UNAVAILABLE';
}

function decorate(row: MarketSignalRow): MarketSignalsView['signals'][number] {
  return {
    ...row,
    stateJa: MARKET_SIGNAL_STATE_JA[row.state],
    glossaryKey: MARKET_SIGNAL_STATE_GLOSSARY[row.state] ?? '',
  };
}

export function marketSignalsView(
  projection: {
    marketSignals?: MarketSignalsProjection | null;
    families?: Record<string, { status?: string | null; conditionMet?: boolean | null }> | null;
  } | null | undefined,
): MarketSignalsView | null {
  if (!projection) return null;
  const server = projection.marketSignals;
  const serverRows = Array.isArray(server?.signals) ? server!.signals! : null;
  if (serverRows && serverRows.length === MARKET_SIGNAL_DEFINITIONS.length) {
    const rows: MarketSignalRow[] = MARKET_SIGNAL_DEFINITIONS.map((def) => {
      const raw = serverRows.find((r) => r.id === def.id);
      const state = raw && STATES.has(String(raw.state)) ? raw.state as MarketSignalState : 'UNAVAILABLE';
      return {
        id: def.id, family: def.family, nameEn: def.nameEn, nameJa: def.nameJa,
        state, status: raw?.status ?? null, conditionMet: raw?.conditionMet ?? null,
      };
    });
    // The numerator is always recounted from the per-signal states so a
    // server count can never disagree with what is shown.
    const activeCount = rows.filter((r) => r.state === 'ACTIVE').length;
    return {
      label: 'MARKET SIGNALS', total: rows.length, activeCount,
      countLabel: `${activeCount} / ${rows.length}`, source: 'server',
      signals: rows.map(decorate),
    };
  }
  const families = projection.families ?? {};
  const rows: MarketSignalRow[] = MARKET_SIGNAL_DEFINITIONS.map((def) => {
    const fam = families[def.family];
    return {
      id: def.id, family: def.family, nameEn: def.nameEn, nameJa: def.nameJa,
      state: signalStateFromFamily(fam),
      status: fam?.status ?? null, conditionMet: fam?.conditionMet ?? null,
    };
  });
  const activeCount = rows.filter((r) => r.state === 'ACTIVE').length;
  return {
    label: 'MARKET SIGNALS', total: rows.length, activeCount,
    countLabel: `${activeCount} / ${rows.length}`, source: 'derived',
    signals: rows.map(decorate),
  };
}
