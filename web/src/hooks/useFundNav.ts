import { useEffect, useState } from 'react';

// 投信(基準価額) follow (v10.60) — daily NAV + 前日比 for JP mutual funds by
// 協会コード, from the 投信総合ライブラリー (free). Twelve Data does NOT cover
// these open-end funds, so this is the real source for following 投信.
export interface FundNav {
  code: string;
  name: string;
  navYen: number;
  changePct: number | null;
  date: string;
  status: string;
}

export function useFundNav(codes?: string[]) {
  const [funds, setFunds] = useState<FundNav[]>([]);
  const [loading, setLoading] = useState(true);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  useEffect(() => {
    let alive = true;
    const base = backend?.replace(/\/$/, '');
    async function load() {
      if (!base) { setLoading(false); return; }
      try {
        const q = codes && codes.length ? `?codes=${codes.join(',')}` : '';
        const d = await fetch(`${base}/api/argus/fund-nav${q}`).then((r) => r.json());
        if (alive && Array.isArray(d?.funds)) setFunds(d.funds);
      } catch { /* keep last */ }
      finally { if (alive) setLoading(false); }
    }
    load();
    const t = window.setInterval(load, 6 * 60 * 60 * 1000); // NAV is daily
    return () => { alive = false; window.clearInterval(t); };
  }, [backend, codes]);

  return { funds, loading };
}
