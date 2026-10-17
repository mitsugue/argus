const STORAGE_KEY = 'argus.assetDeskRiskLines.v1';

type RiskLines = Record<string, number>;

function readAll(): RiskLines {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) as unknown : {};
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed)
      .filter(([, value]) => Number.isFinite(value) && Number(value) > 0)
      .map(([symbol, value]) => [symbol.toUpperCase(), Number(value)]));
  } catch {
    return {};
  }
}

export function readAssetRiskLine(symbol: string): number | null {
  return readAll()[symbol.toUpperCase()] ?? null;
}

export function saveAssetRiskLine(symbol: string, value: number | null): void {
  const all = readAll();
  const key = symbol.toUpperCase();
  if (Number.isFinite(value) && Number(value) > 0) all[key] = Number(value);
  else delete all[key];
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
  } catch {
    // Device storage can be unavailable in private mode. The current screen
    // still keeps its controlled value; no server fallback is attempted.
  }
}

export const ASSET_RISK_LINE_STORAGE_KEY = STORAGE_KEY;
