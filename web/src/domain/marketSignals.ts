// v13.5.38 — MARKET SIGNALS (SIG-01..07) owner-facing view.
//
// The backend projects the seven evidence families into `marketSignals`
// inside the JP_MARKET_ENGINE market view (argus_market_signals.py). This module renders
// that projection; when an older backend omits it, the same counting rule is
// derived from the families so the surface never disappears and never lies:
// ACTIVE counts, everything else is shown as its own truthful state.
import { MARKET_SIGNAL_STATE_GLOSSARY } from './glossary';

export type MarketSignalState =
  | 'ACTIVE' | 'CLEAR' | 'DATA_GATED' | 'STALE' | 'LICENSE_BLOCKED' | 'NOT_APPLICABLE' | 'UNAVAILABLE';

export interface MarketSignalRow {
  id: string;
  family: string;
  nameEn: string;
  nameJa: string;
  state: MarketSignalState;
  status?: string | null;
  conditionMet?: boolean | null;
  ruleStatus?: string | null;
  valuationBasis?: string | null;
  conditionRuleJa?: string | null;
  /** Why a DATA_GATED row is gated: no source rule vs. missing data (server-provided). */
  gateNoteJa?: string | null;
  /** The value, its week and when it was published (2026-10-04, a situation summary). */
  factNoteJa?: string | null;
  ruleId?: string;
  lineage?: string;
  value?: number;
  knowledgeTime?: string | null;
  sourcePeriodEnd?: string | null;
  distance?: { signedFromBoundary: number; unit: string; operator: string; atBoundary: boolean; boundaryCounts: boolean } | null;
  performance?: { ruleId: string; status: string; evaluated: number;
    availabilityBasis?: string;
    horizons?: Record<string, { evaluated: number; falls: number; baselineFallShare: number | null }> };
}

export interface MarketSignalsProjection {
  schemaVersion?: string;
  total?: number;
  activeCount?: number;
  countLabel?: string;
  countRule?: string;
  informationCutoff?: string;
  rejectedEvidence?: boolean;
  countPredictsCrash?: boolean;
  actionAuthority?: boolean;
  signals?: Array<{
    id?: string; family?: string; nameEn?: string; nameJa?: string;
    state?: string; status?: string | null; conditionMet?: boolean | null;
    gateNoteJa?: string | null; factNoteJa?: string | null;
    ruleStatus?: string | null; valuationBasis?: string | null; conditionRuleJa?: string | null;
    ruleId?: string; lineage?: string; reasonJa?: string; value?: number;
    knowledgeTime?: string | null; sourcePeriodEnd?: string | null;
    distance?: MarketSignalRow['distance'];
    performance?: MarketSignalRow['performance'];
  }>;
}

export interface MarketSignalsView {
  label: 'MARKET SIGNALS';
  total: number;
  activeCount: number;
  countLabel: string;
  source: 'server' | 'derived';
  kind?: 'legacy' | 'warning';
  measurableCount?: number;
  signals: Array<MarketSignalRow & { stateJa: string; glossaryKey: string }>;
}

export const MARKET_SIGNAL_DEFINITIONS: ReadonlyArray<{
  id: string; family: string; nameEn: string; nameJa: string;
}> = [
  { id: 'SIG-01', family: 'D01', nameEn: 'Margin / Credit Balance', nameJa: '信用残' },
  { id: 'SIG-02', family: 'D02', nameEn: '1570 / Supply-Demand', nameJa: '1570制度信用倍率' },
  { id: 'SIG-03', family: 'D03', nameEn: 'Relative Strength', nameJa: '相対力' },
  { id: 'SIG-04', family: 'D04', nameEn: 'Japan Earnings / Valuation', nameJa: 'EPS基準・バリュエーション' },
  { id: 'SIG-05', family: 'D05', nameEn: 'Foreign Investor Flow', nameJa: '海外フロー' },
  { id: 'SIG-06', family: 'D06', nameEn: 'VIX / MACD', nameJa: 'VIX・MACD' },
  { id: 'SIG-07', family: 'D07', nameEn: 'Earnings Reaction', nameJa: '決算反応' },
];

export const MARKET_SIGNAL_STATE_JA: Record<MarketSignalState, string> = {
  ACTIVE: '点灯', CLEAR: '消灯', DATA_GATED: '判定不能', STALE: '古い',
  LICENSE_BLOCKED: '要ライセンス', NOT_APPLICABLE: '該当なし', UNAVAILABLE: '欠測',
};

const STATES: ReadonlySet<string> = new Set(
  ['ACTIVE', 'CLEAR', 'DATA_GATED', 'STALE', 'LICENSE_BLOCKED', 'NOT_APPLICABLE', 'UNAVAILABLE']);

/** The single counting rule (mirrors argus_market_signals.signal_state). */
export function signalStateFromFamily(
  row: { status?: string | null; conditionMet?: boolean | null; ruleStatus?: string | null } | null | undefined,
): MarketSignalState {
  if (!row || typeof row !== 'object') return 'UNAVAILABLE';
  if (row.status === 'AVAILABLE') {
    if (row.ruleStatus === 'RULE_NOT_DEFINED') return 'DATA_GATED';
    if (row.conditionMet === true) return 'ACTIVE';
    if (row.conditionMet === false) return 'CLEAR';
    return 'DATA_GATED';
  }
  if (row.status === 'STALE') return 'STALE';
  if (row.status === 'LICENSE_BLOCKED') return 'LICENSE_BLOCKED';
  if (row.status === 'NOT_APPLICABLE') return 'NOT_APPLICABLE';
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
    warningSignals?: MarketSignalsProjection | null;
    informationCutoff?: string;
    families?: Record<string, { status?: string | null; conditionMet?: boolean | null;
      ruleStatus?: string | null; valuationBasis?: string | null; conditionRuleJa?: string | null }> | null;
  } | null | undefined,
): MarketSignalsView | null {
  if (!projection) return null;
  if (projection.warningSignals != null) {
    const warning = projection.warningSignals;
    const candidates = warning.signals;
    const adoptedVersion = warning.schemaVersion === 'jp-warning-conditions-v3';
    const expectedRule = (family: string) => `${adoptedVersion && ['D03', 'D04', 'D07'].includes(family)
      ? 'jp-warning-conditions-v3' : 'jp-warning-conditions-v2'}.${family}`;
    const valid = typeof warning.informationCutoff === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(warning.informationCutoff)
      && Number.isFinite(Date.parse(warning.informationCutoff)) && (adoptedVersion || warning.schemaVersion === 'jp-warning-conditions-v2')
      && warning.countPredictsCrash === false && warning.actionAuthority === false
      && warning.rejectedEvidence === false
      && warning.informationCutoff === projection.informationCutoff
      && Array.isArray(candidates) && candidates.length === 7
      && MARKET_SIGNAL_DEFINITIONS.every(def => candidates.filter(row => row.id === def.id.replace('SIG-', 'WARN-')
        && row.family === def.family && row.ruleId === expectedRule(def.family)).length === 1);
    const names = ['信用売り残が少ない', '日経レバの制度信用倍率', '日本株の優位性低下', '推計EPSの下方修正',
      '海外投資家の売り越し', 'VIXのMACDが上向き', '好決算でも株価下落'];
    const rows = MARKET_SIGNAL_DEFINITIONS.map((def, index): MarketSignalRow => {
      const raw = valid ? candidates?.find(row => row.family === def.family) : null;
      let state: MarketSignalState = raw && STATES.has(String(raw.state)) ? raw.state as MarketSignalState : 'UNAVAILABLE';
      if ([2, 3, 6].includes(index) && (!adoptedVersion || raw?.lineage !== 'ARGUS_VALIDATION_RULE')
        && (state === 'ACTIVE' || state === 'CLEAR')) state = 'DATA_GATED';
      if (raw?.ruleStatus === 'RULE_NOT_DEFINED' && (state === 'ACTIVE' || state === 'CLEAR')) state = 'DATA_GATED';
      if ((state === 'ACTIVE' || state === 'CLEAR') && (raw?.status !== 'AVAILABLE'
        || raw.conditionMet !== (state === 'ACTIVE')
        || typeof raw.value !== 'number' || !Number.isFinite(raw.value)
        || typeof raw.knowledgeTime !== 'string' || !/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(raw.knowledgeTime)
        || !Number.isFinite(Date.parse(raw.knowledgeTime)) || Date.parse(raw.knowledgeTime) > Date.parse(warning.informationCutoff ?? ''))) state = 'DATA_GATED';
      return { ...def, nameJa: names[index], state, status: raw?.status, conditionMet: raw?.conditionMet,
        ruleId: raw?.ruleId, ruleStatus: raw?.ruleStatus, lineage: raw?.lineage,
        conditionRuleJa: raw?.conditionRuleJa, value: raw?.value,
        knowledgeTime: raw?.knowledgeTime, sourcePeriodEnd: raw?.sourcePeriodEnd,
        distance: state === 'ACTIVE' || state === 'CLEAR' ? raw?.distance : null,
        gateNoteJa: raw?.reasonJa ?? (valid ? null : '警戒条件の版・根拠・時点を確認できません'),
        factNoteJa: raw?.factNoteJa, valuationBasis: raw?.valuationBasis,
        performance: raw && raw.performance?.ruleId === raw.ruleId ? raw.performance : undefined };
    });
    const activeCount = rows.filter(row => row.state === 'ACTIVE').length;
    return { label: 'MARKET SIGNALS', total: 7, activeCount, countLabel: `${activeCount} / 7`,
      source: 'server', kind: 'warning', measurableCount: rows.filter(row => ['ACTIVE', 'CLEAR'].includes(row.state)).length,
      signals: rows.map(decorate) };
  }
  const server = projection.marketSignals;
  const serverRows = Array.isArray(server?.signals) ? server!.signals! : null;
  if (serverRows && serverRows.length === MARKET_SIGNAL_DEFINITIONS.length) {
    const rows: MarketSignalRow[] = MARKET_SIGNAL_DEFINITIONS.map((def) => {
      const raw = serverRows.find((r) => r.id === def.id);
      const state = raw?.ruleStatus === 'RULE_NOT_DEFINED' && raw?.status === 'AVAILABLE' ? 'DATA_GATED'
        : raw && STATES.has(String(raw.state)) ? raw.state as MarketSignalState : 'UNAVAILABLE';
      return {
        id: def.id, family: def.family, nameEn: def.nameEn, nameJa: def.nameJa,
        state, status: raw?.status ?? null, conditionMet: raw?.conditionMet ?? null,
        ruleStatus: raw?.ruleStatus ?? null, valuationBasis: raw?.valuationBasis ?? null,
        conditionRuleJa: raw?.conditionRuleJa ?? null,
        gateNoteJa: typeof raw?.gateNoteJa === 'string' && raw.gateNoteJa ? raw.gateNoteJa : null,
        factNoteJa: typeof raw?.factNoteJa === 'string' && raw.factNoteJa ? raw.factNoteJa : null,
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
      ruleStatus: fam?.ruleStatus ?? null, valuationBasis: fam?.valuationBasis ?? null,
      conditionRuleJa: fam?.conditionRuleJa ?? null,
    };
  });
  const activeCount = rows.filter((r) => r.state === 'ACTIVE').length;
  return {
    label: 'MARKET SIGNALS', total: rows.length, activeCount,
    countLabel: `${activeCount} / ${rows.length}`, source: 'derived',
    signals: rows.map(decorate),
  };
}
