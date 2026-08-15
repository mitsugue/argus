import { useEffect, useState } from 'react';
import type { AssetItem } from '../types/assetItem';

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

/** Deterministic catalog match shared by Holdings, exposure, and FIRE views. */
export function fundNavForAsset(asset: AssetItem, funds: FundNav[]): FundNav | null {
  const symbol = asset.symbol.toUpperCase();
  const name = `${asset.displayName || ''} ${asset.displayNameJa || ''}`.toLowerCase();
  const matches = (keyword: string) =>
    symbol.includes(keyword) || name.includes(keyword.toLowerCase());
  for (const fund of funds) {
    const fundName = (fund.name || '').toLowerCase();
    if (fundName.includes('全世界')
      && (matches('ACWI') || name.includes('全世界') || name.includes('オルカン')
        || name.includes('オール'))) return fund;
    if (fundName.includes('s&p500')
      && (matches('SP500') || matches('S&P') || name.includes('米国'))) return fund;
    if (fundName.includes('国内')
      && (matches('N225') || matches('NIKKEI') || name.includes('国内')
        || name.includes('日経'))) return fund;
  }
  return null;
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
