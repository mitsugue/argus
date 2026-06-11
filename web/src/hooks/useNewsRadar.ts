import { useEffect, useState } from 'react';

// Black-swan CAUSE radar from /api/argus/news-radar (news-v1): crisis-grade
// headline counts per theme (GDELT, 6h window, 30-min cache). Honest framing:
// counts are a crude reference signal, not verified facts.

export type NewsLevel = 'calm' | 'elevated' | 'high' | 'unknown';

export interface NewsHeadline { title: string; url: string; source: string; seen: string; }
export interface NewsTheme {
  key: string; labelJa: string; count: number;
  level: 'calm' | 'elevated' | 'high'; headlines: NewsHeadline[];
}
export interface NewsRadar {
  status: 'live' | 'unavailable';
  asOf: string; engineVersion: string;
  level: NewsLevel; topThemeKey: string | null;
  themes: NewsTheme[]; noteJa: string; dataLimitations: string[];
}

interface State { data: NewsRadar | null; loading: boolean; }

export function useNewsRadar(): State {
  const [state, setState] = useState<State>({ data: null, loading: true });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) { setState({ data: null, loading: false }); return; }
    let cancelled = false;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 12_000);
    (async () => {
      try {
        const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/news-radar', { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as NewsRadar;
        if (!cancelled) setState({ data, loading: false });
      } catch {
        clearTimeout(timer);
        if (!cancelled) setState({ data: null, loading: false });
      }
    })();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  return state;
}
