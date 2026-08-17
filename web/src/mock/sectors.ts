import type { NetworkSnapshot, SectorLink, SectorNode } from '../types/sector';

/**
 * 12 macro sectors that map roughly to GICS / typical macro buckets,
 * plus a handful of cross-sector links so the force graph has structure.
 */
// Curated sector palette — muted, harmonious-but-distinguishable hues so each
// bubble reads as its own sector at a glance against the light background.
const SECTOR_SEED: Array<Omit<SectorNode, 'flow' | 'alert'> & { alert?: SectorNode['alert'] }> = [
  { id: 'tech',       label: 'TECH',        depth: 'sector', parentId: null, liquidity: 1900, themeTag: 'AI_INFRA',     color: '#3a6ea8' },
  { id: 'semi',       label: 'SEMI',        depth: 'sector', parentId: null, liquidity: 1450, themeTag: 'AI_INFRA',     color: '#6e4fa0' },
  { id: 'finance',    label: 'FINANCIALS',  depth: 'sector', parentId: null, liquidity: 1300,                            color: '#b08a3a' },
  { id: 'energy',     label: 'ENERGY',      depth: 'sector', parentId: null, liquidity: 1180,                            color: '#b86a2c' },
  { id: 'commodity',  label: 'COMMODITIES', depth: 'sector', parentId: null, liquidity: 1100, themeTag: 'COPPER_CYCLE',  color: '#a05038' },
  { id: 'defense',    label: 'DEFENSE',     depth: 'sector', parentId: null, liquidity: 760,  alert: 'alert', themeTag: 'GEOPOLITICS', color: '#a83a3a' },
  { id: 'healthcare', label: 'HEALTH',      depth: 'sector', parentId: null, liquidity: 1020,                            color: '#3a9090' },
  { id: 'consumer',   label: 'CONSUMER',    depth: 'sector', parentId: null, liquidity: 870,                             color: '#9c5278' },
  { id: 'realestate', label: 'REIT',        depth: 'sector', parentId: null, liquidity: 540,                             color: '#7a8a4a' },
  { id: 'utilities',  label: 'UTILITIES',   depth: 'sector', parentId: null, liquidity: 460,                             color: '#5a6e8a' },
  { id: 'crypto',     label: 'CRYPTO',      depth: 'sector', parentId: null, liquidity: 690,  alert: 'warm',             color: '#c8742c' },
  { id: 'jp-small',   label: 'JP SMALL',    depth: 'sector', parentId: null, liquidity: 380,  themeTag: 'JP_IPO_WAVE',   color: '#3a8ab8' },
];

const LINK_SEED: SectorLink[] = [
  { source: 'tech',       target: 'semi',       weight: 0.9 },
  { source: 'semi',       target: 'commodity',  weight: 0.4 },
  { source: 'commodity',  target: 'energy',     weight: 0.7 },
  { source: 'energy',     target: 'defense',    weight: 0.5 },
  { source: 'defense',    target: 'finance',    weight: 0.3 },
  { source: 'finance',    target: 'realestate', weight: 0.6 },
  { source: 'finance',    target: 'utilities',  weight: 0.4 },
  { source: 'healthcare', target: 'consumer',   weight: 0.5 },
  { source: 'consumer',   target: 'tech',       weight: 0.4 },
  { source: 'crypto',     target: 'finance',    weight: 0.45 },
  { source: 'crypto',     target: 'tech',       weight: 0.3 },
  { source: 'jp-small',   target: 'semi',       weight: 0.55 },
  { source: 'jp-small',   target: 'tech',       weight: 0.3 },
  { source: 'commodity',  target: 'jp-small',   weight: 0.25 },
];

export function seedNetwork(): NetworkSnapshot {
  const nodes: SectorNode[] = SECTOR_SEED.map((s) => ({
    ...s,
    flow: 0,
    alert: s.alert ?? 'normal',
  }));
  const totalLiquidity = nodes.reduce((sum, n) => sum + n.liquidity, 0);
  return { nodes, links: LINK_SEED.map((l) => ({ ...l })), totalLiquidity };
}

/**
 * "Breathe" the network — each tick perturbs every sector's liquidity
 * slightly while keeping the system total fixed. Models money sloshing
 * between sectors rather than appearing / disappearing.
 */
export function breatheNetwork(snap: NetworkSnapshot): NetworkSnapshot {
  const next = snap.nodes.map((n) => {
    const noise = (Math.random() - 0.5) * 0.04; // ±2 %
    const flow = noise + (Math.random() - 0.5) * 0.02;
    return {
      ...n,
      // Decay flow toward 0 then re-noise so direction signal lingers
      flow: Math.max(-1, Math.min(1, n.flow * 0.6 + flow * 6)),
      liquidity: Math.max(80, n.liquidity * (1 + noise)),
    };
  });
  // Renormalize so the sum equals the original total — "money is conserved"
  const sum = next.reduce((s, n) => s + n.liquidity, 0);
  const scale = snap.totalLiquidity / sum;
  const renormalized = next.map((n) => ({
    ...n,
    liquidity: +(n.liquidity * scale).toFixed(2),
  }));
  return { nodes: renormalized, links: snap.links, totalLiquidity: snap.totalLiquidity };
}
