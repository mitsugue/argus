import { validMarketBrief, type MarketBrief } from './marketBrief';
import { readableBriefEdition } from './presentationIntent';
const key = 'argus.marketBrief.session.v1';
const maxBytes = 2_000_000;
/** One complete public edition; no credential or owner explanation. */
export function readSessionBrief(): MarketBrief | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw || raw.length > maxBytes) return null;
    const value: unknown = JSON.parse(raw);
    return validMarketBrief(value) && value.unifiedSummary?.ownerContextAvailable === false
      ? readableBriefEdition(value) : null;
  } catch { return null; }
}
export function saveSessionBrief(value: MarketBrief | null): void {
  const edition = readableBriefEdition(value);
  if (!edition || edition.unifiedSummary?.ownerContextAvailable !== false) return;
  try { const raw = JSON.stringify(edition); if (raw.length <= maxBytes) sessionStorage.setItem(key, raw); }
  catch { /* Optional display cache; original stamps remain authoritative. */ }
}
export function clearSessionBrief(): void {
  try { sessionStorage.removeItem(key); } catch { /* unavailable storage */ }
}
