import { markLocalEdit } from './vault';
// Per-symbol research notes (research-notes-v1, v10.25) — the place to paste
// back Gemini Pro / GPT Pro OSINT answers so the qualitative research lives
// alongside the stock and survives local JSON export. Existing encrypted
// recovery envelopes remain readable, but the public browser does not push.

const KEY = 'argus.research.v1';

export interface ResearchNote { text: string; savedAt: number; }

function readAll(): Record<string, ResearchNote> {
  try {
    const raw = localStorage.getItem(KEY);
    const o = raw ? JSON.parse(raw) : {};
    return o && typeof o === 'object' ? o : {};
  } catch {
    return {};
  }
}

export function getNote(symbol: string): ResearchNote | null {
  return readAll()[symbol] ?? null;
}

export function saveNote(symbol: string, text: string): void {
  try {
    const all = readAll();
    if (text.trim()) all[symbol] = { text: text.trim(), savedAt: Date.now() };
    else delete all[symbol];
    localStorage.setItem(KEY, JSON.stringify(all));
    markLocalEdit();   // record local freshness; public cloud push is unavailable
  } catch { /* ignore */ }
}
