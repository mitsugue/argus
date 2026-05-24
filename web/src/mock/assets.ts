import type { AssetNode, AssetTree } from '../types/asset';

/**
 * World-scale snapshot of where money currently sits, mock-driven.
 * Numbers are in trillions (mock); the absolute scale doesn't matter — the
 * pack layout cares only about relative size.
 */
export function seedAssets(): AssetTree {
  return {
    id: 'root',
    value: 0,
    children: [
      { id: 'cash',  label: 'CASH',  value: 18.5, themeTag: 'GLOBAL_M2',  heat: 0.05 },
      { id: 'bond',  label: 'BOND',  value: 26.0, themeTag: 'YIELD_PEAK', heat: -0.12 },
      {
        id: 'stock',
        label: 'STOCK',
        value: 0,
        heat: 0.22,
        children: [
          { id: 'it-semi', label: 'IT/SEMI', value: 14.2, themeTag: 'AI_INFRA', heat: 0.45 },
          { id: 'bank',    label: 'BANK',    value: 7.8,  heat: 0.12 },
          { id: 'mfg',     label: 'MFG',     value: 9.1,  heat: -0.08 },
          { id: 'energy',  label: 'ENERGY',  value: 5.6,  heat: 0.32 },
          { id: 'health',  label: 'HEALTH',  value: 6.8,  heat: -0.18 },
          { id: 'consume', label: 'CONSUMER', value: 5.4, heat: -0.05 },
        ],
      },
      { id: 'reit',   label: 'REIT',   value: 4.2, heat: -0.22 },
      { id: 'crypto', label: 'CRYPTO', value: 3.6, alert: true, themeTag: 'BTC_RUN', heat: 0.58 },
      { id: 'fx',     label: 'FX',     value: 7.1, heat: 0.02 },
    ],
  };
}

/**
 * Perturb leaf values while conserving the global total.
 * Models money sloshing between asset classes / sub-sectors.
 */
export function breatheAssets(tree: AssetTree): AssetTree {
  // Recursively gather leaves with mutable references
  const leaves: AssetNode[] = [];
  const walk = (n: AssetNode | AssetTree) => {
    if ('children' in n && n.children && n.children.length) {
      n.children.forEach(walk);
    } else if ('value' in n && typeof n.value === 'number') {
      leaves.push(n as AssetNode);
    }
  };
  walk(tree);
  const originalTotal = leaves.reduce((s, l) => s + l.value, 0);
  const perturbed = leaves.map((l) => {
    const noise = (Math.random() - 0.5) * 0.06; // ±3 %
    return { ...l, value: Math.max(0.5, l.value * (1 + noise)) };
  });
  const sum = perturbed.reduce((s, l) => s + l.value, 0);
  const scale = originalTotal / sum;
  const valById = new Map(perturbed.map((p) => [p.id, +(p.value * scale).toFixed(3)]));

  // Rebuild a fresh tree with the new leaf values
  const rebuild = <T extends AssetNode | AssetTree>(n: T): T => {
    if ('children' in n && n.children && n.children.length) {
      return { ...n, children: n.children.map(rebuild) } as T;
    }
    const v = valById.get((n as AssetNode).id);
    return { ...n, value: v ?? (n as AssetNode).value } as T;
  };
  return rebuild(tree);
}
