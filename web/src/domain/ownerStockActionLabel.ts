// 2026-10-25 (owner): 「WAIT · 最終判断 DATA GATED」を、保有数が不明なためと分かる
// 日本語の短い表示にする。判断の中身は変えない — the label only reads the
// decision. Holdings entry was retired in 13.8, so a registered stock's owner
// context is UNKNOWN and the decision is data-gated for that reason alone; any
// other missing or conflicting evidence keeps the general "データ待ち".
type GatedReading = {
  status: 'EVALUATED' | 'DATA_GATED';
  primaryAction: string;
  missingReasonCodes: readonly string[];
  conflictReasonCodes: readonly string[];
};

const OWNER_CONTEXT_ONLY = 'owner_context_unknown';

export function ownerStockActionJa(result: GatedReading | null | undefined): string {
  const action = result?.primaryAction ?? 'WAIT';
  if (!result || result.status !== 'DATA_GATED') return `${action} · 最終判断`;
  const ownerOnly = result.conflictReasonCodes.length === 0
    && result.missingReasonCodes.length > 0
    && result.missingReasonCodes.every((code) => code === OWNER_CONTEXT_ONLY);
  return ownerOnly ? '見送り · 保有数が不明なため保留' : '見送り · データ待ち';
}
