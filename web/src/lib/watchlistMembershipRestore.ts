import type { AssetItem } from '../types/assetItem';

// Membership is not an asset backup. Keep every local record and archived field.
export function mergeWatchlistMembership(local: unknown, members: unknown, now: number): { assets: AssetItem[]; added: number } {
  const record = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);
  if (!Array.isArray(local) || local.some(x => !record(x) || typeof x.id !== 'string'
    || typeof x.symbol !== 'string' || typeof x.market !== 'string')) throw Error('端末の銘柄記録を確認できません。復元を中止しました');
  if (!Array.isArray(members) || members.length > 200 || members.some(x => !record(x)
    || !['JP', 'US', 'CRYPTO'].includes(String(x.market)) || typeof x.symbol !== 'string'
    || !x.symbol.trim() || x.symbol.length > 100 || (x.enabled !== undefined && typeof x.enabled !== 'boolean')
    || (x.name !== undefined && typeof x.name !== 'string'))) throw Error('保存済みの銘柄情報が不正です。復元を中止しました');
  const assets = [...local] as AssetItem[];
  const key = (market: string, symbol: string) => `${market}:${symbol.trim().toUpperCase()}`;
  const keys = new Set(assets.map(x => key(x.market, x.symbol)));
  const ids = new Set(assets.map(x => x.id));
  let order = assets.reduce((n, x) => Math.max(n, Number.isFinite(x.sortOrder) ? x.sortOrder + 1 : 0), 0);
  for (const m of members as { market: 'JP' | 'US' | 'CRYPTO'; symbol: string; name?: string; enabled?: boolean }[]) {
    const symbol = m.symbol.trim();
    const identity = key(m.market, symbol);
    if (keys.has(identity)) continue;
    const base = `${m.market.toLowerCase()}-${symbol.toLowerCase()}`;
    let id = base;
    for (let suffix = 1; ids.has(id); suffix++) id = `${base}-restored-${suffix}`;
    const name = m.name?.trim() || symbol;
    assets.push({ id, symbol, displayName: name, displayNameJa: m.name?.trim() || undefined,
      market: m.market, assetType: m.market === 'JP' ? 'jp_equity' : m.market === 'US' ? 'us_equity' : 'crypto',
      source: m.market === 'JP' ? 'jquants' : m.market === 'US' ? 'twelvedata' : 'manual',
      enabled: m.enabled !== false, sortOrder: order++, createdAt: now, updatedAt: now,
      ...(m.market === 'CRYPTO' ? { memo: `coingecko:${symbol.toLowerCase() === 'btc' ? 'bitcoin' : symbol.toLowerCase() === 'eth' ? 'ethereum' : symbol.toLowerCase()}` } : {}) });
    keys.add(identity); ids.add(id);
  }
  return { assets, added: assets.length - local.length };
}
