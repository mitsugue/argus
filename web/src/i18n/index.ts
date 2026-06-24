import { useEffect, useReducer } from 'react';
import { DICT, type Locale, type DictKey } from './locales';

// App-wide localization (v10.123). Default locale = en (owner prefers short
// English action words); ja is a complete alternate. Preference persists locally.
// Switching locale never triggers a paid AI call — UI strings are deterministic
// dictionary lookups; dynamic reasoning uses pre-stored en/ja fields.

const KEY = 'argus.locale.v1';

function read(): Locale {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'ja' || v === 'en' ? v : 'ja';   // default Japanese (v10.129): long
    // copy reads in Japanese; only the punchy action keywords stay English.
  } catch { return 'ja'; }
}

let _locale: Locale = read();
const listeners = new Set<() => void>();

export function getLocale(): Locale { return _locale; }

export function setLocale(l: Locale): void {
  _locale = l;
  try { localStorage.setItem(KEY, l); } catch { /* ignore */ }
  listeners.forEach((f) => f());
}

/** Subscribe a component to locale changes (re-renders on switch). */
export function useLocale(): Locale {
  const [, force] = useReducer((x) => x + 1, 0);
  useEffect(() => {
    listeners.add(force);
    return () => { listeners.delete(force); };
  }, []);
  return _locale;
}

/** Translate a typed key for the active locale (falls back to en, then the key). */
export function t(key: DictKey): string {
  return DICT[_locale][key] ?? DICT.en[key] ?? key;
}

/** Always English, regardless of locale — for the punchy "要所" surfaces the owner
    wants in English even in Japanese mode (e.g. page/door titles), v10.130. */
export function tEn(key: DictKey): string {
  return DICT.en[key] ?? key;
}

/** Pick the locale-matching field from a bilingual pair (e.g. reasonEn/reasonJa).
    If the active-locale value is missing, returns the other with an ORIGINAL badge
    hint via the caller — here we just return the best available. */
export function pick(en?: string | null, ja?: string | null): string {
  if (_locale === 'ja') return (ja ?? en ?? '');
  return (en ?? ja ?? '');
}

export type { Locale, DictKey };
