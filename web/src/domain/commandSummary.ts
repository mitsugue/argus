// Command Summary (v10.122) — ARGUS synthesizes all inputs into ONE resolved
// command so the owner never reconciles parallel states (PAUSE vs EVENT WAIT vs
// HIGH vs PARTIAL …). Deterministic; localizable (en/ja templates, no AI call).

import { resolveSignal, SIGNALS, type SignalCode, type DataQuality, type OwnerState } from './actionLevel';

export interface Driver {
  code: string;
  severity: 'high' | 'medium' | 'low';
  labelEn: string;
  labelJa: string;
}

export interface CommandSummary {
  primaryCommandCode: string;
  primaryCommandEn: string;
  primaryCommandJa: string;
  signalCode: SignalCode;
  signalLevel: number;
  existingPositionCode: string;
  riskLevel: string;
  dataQuality: DataQuality;
  confidence: number | null;
  drivers: Driver[];           // ≤ 3, ranked
  reasonEn: string;
  reasonJa: string;
  nextReviewEn: string;
  nextReviewJa: string;
  context: { globalRegime: string; jpOverlay: string; ownerRisk: string };
}

// Level → human PRIMARY COMMAND (the largest text; not the abstract signal word).
const PRIMARY: Record<SignalCode, { code: string; en: string; ja: string }> = {
  ENTER: { code: 'ENTRY_ALLOWED', en: 'ENTRY ALLOWED', ja: '新規購入可' },
  PREPARE: { code: 'WAIT_FOR_SETUP', en: 'WAIT FOR SETUP', ja: '条件待ち' },
  HOLD_ONLY: { code: 'HOLD_EXISTING_ONLY', en: 'HOLD EXISTING ONLY', ja: '既存保有のみ' },
  PAUSE: { code: 'NO_NEW_ENTRY', en: 'NO NEW ENTRY', ja: '新規購入禁止' },
  REVIEW: { code: 'REASSESS_NOW', en: 'REASSESS NOW', ja: '直ちに再点検' },
  DEFEND: { code: 'PROTECT_CAPITAL', en: 'PROTECT CAPITAL', ja: '資金防衛優先' },
  EXIT: { code: 'EXIT_POSITION', en: 'EXIT POSITION', ja: '撤退判断' },
};

const SEV_RANK = { high: 0, medium: 1, low: 2 };
const fmtEnum = (s?: string) => (s || '').replace(/_/g, ' ');

export interface SummaryInput {
  legacyAction: string;
  globalRegime?: string;
  jpOverlay?: string;            // NORMAL | CAUTION | RISK_OFF_WATCH
  ownerRisk?: string;            // NONE | REVIEW_REQUIRED | ...
  risk?: string;
  isPartial?: boolean;
  dataQuality?: DataQuality;
  confidence?: number | null;
  ownerState?: OwnerState;
  nextConditionJa?: string;      // backend (ja) — used as the ja next-review
}

function buildDrivers(inp: SummaryInput): Driver[] {
  const out: Driver[] = [];
  const ownerRisk = inp.ownerRisk && inp.ownerRisk !== 'NONE';
  if (ownerRisk) {
    out.push({ code: 'OWNER_POSITION_RISK', severity: 'high',
      labelEn: 'Held asset under review', labelJa: '保有銘柄に警戒' });
  }
  if (inp.globalRegime === 'EVENT_WAIT') {
    out.push({ code: 'HIGH_IMPACT_EVENT_NEAR', severity: 'high',
      labelEn: 'Major event near', labelJa: '重要イベント接近' });
  }
  if (inp.jpOverlay === 'RISK_OFF_WATCH' || inp.jpOverlay === 'CAUTION') {
    out.push({ code: 'JP_INTRADAY_CAUTION', severity: inp.jpOverlay === 'RISK_OFF_WATCH' ? 'high' : 'medium',
      labelEn: 'Japan intraday caution', labelJa: '日本株は日中警戒' });
  }
  const dq = inp.dataQuality ?? (inp.isPartial ? 'PARTIAL' : 'LIVE');
  if (['PARTIAL', 'DELAYED', 'STALE', 'UNKNOWN', 'UNAVAILABLE'].includes(dq)) {
    out.push({ code: 'PARTIAL_DATA', severity: 'medium', labelEn: 'Partial data', labelJa: '部分データ' });
  }
  if (String(inp.risk).toLowerCase() === 'high' && out.length < 3) {
    out.push({ code: 'ELEVATED_RISK', severity: 'medium', labelEn: 'Elevated risk', labelJa: 'リスク高め' });
  }
  out.sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity]);
  return out.slice(0, 3);
}

export function resolveCommandSummary(inp: SummaryInput): CommandSummary {
  const dq = inp.dataQuality ?? (inp.isPartial ? 'PARTIAL' : 'LIVE');
  const ownerRisk = !!(inp.ownerRisk && inp.ownerRisk !== 'NONE');
  const sig = resolveSignal(inp.legacyAction, {
    downsideOverride: ownerRisk ? 'REVIEW_REQUIRED' : null,
    materialDownside: ownerRisk, dataQuality: dq, ownerState: inp.ownerState,
  });
  const pc = PRIMARY[sig.code];
  const drivers = buildDrivers(inp);

  // One deterministic reason built FROM the drivers (no duplication, localizable).
  const driverEn = drivers.map((d) => d.labelEn.toLowerCase()).join(', ');
  const driverJa = drivers.map((d) => d.labelJa).join('・');
  const blocked = sig.permissions.newEntry === 'BLOCKED';
  const reasonEn = blocked
    ? `New entries remain blocked${driverEn ? ` — ${driverEn}` : ''}.`
    : `New entry is permitted within a defined risk budget${driverEn ? ` — ${driverEn}` : ''}.`;
  const reasonJa = blocked
    ? `新規購入は禁止です${driverJa ? `(${driverJa})` : ''}。`
    : `リスク予算内で新規購入が可能です${driverJa ? `(${driverJa})` : ''}。`;

  const nextReviewJa = inp.nextConditionJa || '市場の広がり・金利・フローの確認後に再評価します。';
  const nextReviewEn = 'Reassess after the listed drivers clear and market breadth, rates and flows confirm.';

  return {
    primaryCommandCode: pc.code, primaryCommandEn: pc.en, primaryCommandJa: pc.ja,
    signalCode: sig.code, signalLevel: sig.level,
    existingPositionCode: sig.permissions.existingPosition,
    riskLevel: String(inp.risk ?? '—').toUpperCase(), dataQuality: dq, confidence: inp.confidence ?? null,
    drivers, reasonEn, reasonJa, nextReviewEn, nextReviewJa,
    context: { globalRegime: fmtEnum(inp.globalRegime), jpOverlay: fmtEnum(inp.jpOverlay), ownerRisk: fmtEnum(inp.ownerRisk) },
  };
}

export { SIGNALS };
