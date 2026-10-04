import { useEffect, useState } from 'react';

// FUTURE MAP (2026-10-04): external views written by the research side to the
// private store; the server validates them. Read once per page view.
export type FutureMapRow = { id: string; periodLabel: string; start: string; end: string; view: string;
  reason: string | null; alt: string | null; level: { low: number; high: number } | null; tag: string;
  tone: 'red' | 'amber' | 'green' | 'grey'; agree: number; emphasis: boolean; changed: boolean;
  result: 'reached' | 'missed' | null; isNow: boolean; past: boolean };
export type FutureMapDoc = {
  schemaVersion: 'argus-future-map-public-v1'; updatedAt: string; today: string; rows: FutureMapRow[];
  status: { position: string; nextAlert: { date: string; label: string }; nextBottom: { date: string; label: string } };
  record: { scored: number; reached: number }; argusValidated: false; actionAuthority: false;
};

export function validFutureMap(value: unknown): value is FutureMapDoc {
  const v = value as FutureMapDoc;
  return !!v && v.schemaVersion === 'argus-future-map-public-v1' && v.actionAuthority === false && v.argusValidated === false
    && !!v.status && typeof v.status.position === 'string' && Array.isArray(v.rows)
    && v.rows.every(r => typeof r.id === 'string' && typeof r.view === 'string' && typeof r.tag === 'string');
}

let cache: { at: number; doc: FutureMapDoc | null } | null = null;
const TTL_MS = 30 * 60_000;

export function useFutureMap(): FutureMapDoc | null {
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? '';
  const [doc, setDoc] = useState<FutureMapDoc | null>(cache?.doc ?? null);
  useEffect(() => {
    if (!base || (cache && Date.now() - cache.at < TTL_MS)) return;
    let live = true;
    fetch(`${base}/api/argus/future-map`, { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null))
      .then(body => {
        const found = body && body.availability === 'AVAILABLE' && validFutureMap(body) ? body : null;
        cache = { at: Date.now(), doc: found };
        if (live) setDoc(found);
      }).catch(() => { /* the card stays absent */ });
    return () => { live = false; };
  }, [base]);
  return doc;
}
