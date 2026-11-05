/** Registered JP display projection only; never mutates analytical quote rows. */
import { useSyncExternalStore } from 'react';
import { exactAuthorityEpoch } from './liveAuthority';
export interface DelayedPrice {
  symbol: string; price: number; changePct: number | null;
  sourceTimestamp: string; receivedAt: string; delaySeconds: number;
  current: boolean; lastError: boolean;
}
interface Document {
  schemaVersion?: string; provider?: string; actionAuthority?: boolean; readAt?: string;
  requestedSymbols?: string[]; symbols?: Record<string, unknown>;
}
let document: Document | null = null;
const listeners = new Set<() => void>();
export function setJpDelayedPriceDocument(value: unknown) {
  if (!value || typeof value !== 'object') return;
  const next = value as Document;
  if (next.schemaVersion !== 'argus-jp-delayed-display-v1' || next.provider !== 'YAHOO_DELAYED'
      || next.actionAuthority !== false) return;
  const readAt = exactAuthorityEpoch(next.readAt);
  if (readAt == null || readAt > Date.now() || readAt < (exactAuthorityEpoch(document?.readAt) ?? 0)) return;
  const rows = { ...document?.symbols };
  for (const s of (next.requestedSymbols ?? []).slice(0, 50)) delete rows[s];
  for (const [s, row] of Object.entries(next.symbols ?? {}).slice(0, 50)) {
    if (/^[0-9][0-9A-Z]{3}$/.test(s)) rows[s] = row;
  }
  document = { ...next, symbols: Object.fromEntries(Object.entries(rows).slice(-50)) };
  for (const listener of listeners) listener();
}
export function useJpDelayedPriceDocument() {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    () => document, () => document);
}
const day = (epoch: number) => new Date(epoch).toLocaleDateString('en-CA', { timeZone: 'Asia/Tokyo' });
export function jpDelayedPrice(doc: Document | null, symbol: string, now = Date.now()): DelayedPrice | null {
  if (doc?.schemaVersion !== 'argus-jp-delayed-display-v1' || doc.provider !== 'YAHOO_DELAYED'
      || doc.actionAuthority !== false || !Number.isFinite(now)) return null;
  const value = doc.symbols?.[symbol.toUpperCase()];
  if (!value || typeof value !== 'object') return null;
  const r = value as Record<string, unknown>;
  const source = exactAuthorityEpoch(r.sourceTimestamp), received = exactAuthorityEpoch(r.receivedAt);
  if (r.symbol !== symbol.toUpperCase() || r.provider !== 'YAHOO_DELAYED' || r.actionAuthority !== false
      || r.realtime !== false || typeof r.price !== 'number' || !Number.isFinite(r.price) || r.price <= 0
      || source == null || received == null || source > received || received > now || day(source) !== day(now)
      || day(received) !== day(now) || typeof r.delaySeconds !== 'number' || !Number.isFinite(r.delaySeconds)
      || r.delaySeconds < 0 || Math.abs(r.delaySeconds - (received - source) / 1000) > 1) return null;
  const lastError = r.lastError != null;
  return { symbol, price: r.price,
    changePct: typeof r.changePct === 'number' && Number.isFinite(r.changePct) ? r.changePct : null,
    sourceTimestamp: r.sourceTimestamp as string, receivedAt: r.receivedAt as string,
    delaySeconds: Math.floor((now - source) / 1000), lastError,
    current: !lastError && now - received <= 180_000 && now - source <= 40 * 60_000 };
}
export function delayedPriceTime(value: string): string {
  return new Date(value).toLocaleTimeString('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit' });
}
