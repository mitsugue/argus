import type { AssetNode, AssetTree } from '../types/asset';

/**
 * World-scale snapshot of where money currently sits, four levels deep.
 *
 *   ROOT
 *   ├── asset class      (CASH / BOND / STOCK / REIT / CRYPTO / FX)
 *   │   ├── sub-category (currency / sector / chain)
 *   │   │   └── instrument (individual ticker / instrument)
 *
 * Tap a bubble with children → drill in; the world multiplies.
 */
export function seedAssets(): AssetTree {
  return {
    id: 'root',
    value: 0,
    children: [
      // ───────────── CASH ─────────────
      {
        id: 'cash', label: 'CASH', value: 0,
        children: [
          { id: 'usd-m2', label: 'USD M2', value: 0, children: [
            { id: 'usd-deposit', label: 'DEPOSIT', value: 18.4 },
            { id: 'usd-mmf',     label: 'MMF',     value: 6.2 },
            { id: 'usd-bills',   label: 'T-BILL',  value: 5.8 },
          ]},
          { id: 'eur-m2', label: 'EUR M2', value: 0, children: [
            { id: 'eur-deposit', label: 'DEPOSIT', value: 9.4 },
            { id: 'eur-mmf',     label: 'MMF',     value: 2.1 },
          ]},
          { id: 'jpy-m2', label: 'JPY M2', value: 0, children: [
            { id: 'jpy-deposit', label: 'DEPOSIT', value: 7.8 },
            { id: 'jpy-yucho',   label: 'YUCHO',   value: 1.4 },
          ]},
          { id: 'cny-m2', label: 'CNY M2', value: 0, children: [
            { id: 'cny-deposit', label: 'DEPOSIT', value: 14.2 },
          ]},
        ],
      },

      // ───────────── BOND ─────────────
      {
        id: 'bond', label: 'BOND', value: 0,
        children: [
          { id: 'ust', label: 'US TREASURY', value: 0, children: [
            { id: 'ust-2y',  label: '2Y',  value: 4.2 },
            { id: 'ust-5y',  label: '5Y',  value: 5.8 },
            { id: 'ust-10y', label: '10Y', value: 8.4 },
            { id: 'ust-30y', label: '30Y', value: 4.6 },
          ]},
          { id: 'jgb', label: 'JGB', value: 0, children: [
            { id: 'jgb-5y',  label: '5Y',  value: 2.4 },
            { id: 'jgb-10y', label: '10Y', value: 4.2 },
            { id: 'jgb-30y', label: '30Y', value: 1.6 },
          ]},
          { id: 'bund', label: 'BUND', value: 0, children: [
            { id: 'bund-10y', label: '10Y', value: 3.1 },
            { id: 'bund-30y', label: '30Y', value: 1.2 },
          ]},
          { id: 'gilt', label: 'GILT', value: 0, children: [
            { id: 'gilt-10y', label: '10Y', value: 1.4 },
          ]},
          { id: 'em-sov', label: 'EM SOV', value: 1.8 },
          { id: 'corp-ig', label: 'CORP IG', value: 3.2 },
          { id: 'corp-hy', label: 'CORP HY', value: 1.1 },
        ],
      },

      // ───────────── STOCK ─────────────
      {
        id: 'stock', label: 'STOCK', value: 0,
        children: [
          { id: 'it-semi', label: 'IT / SEMI', value: 0, themeTag: 'AI_INFRA', children: [
            { id: 'nvda',  label: 'NVDA',  value: 3.4 },
            { id: 'aapl',  label: 'AAPL',  value: 3.1 },
            { id: 'msft',  label: 'MSFT',  value: 3.2 },
            { id: 'goog',  label: 'GOOG',  value: 1.9 },
            { id: 'tsmc',  label: 'TSMC',  value: 0.9 },
            { id: 'asml',  label: 'ASML',  value: 0.4 },
            { id: 'avgo',  label: 'AVGO',  value: 0.7 },
            { id: '6758',  label: '6758',  value: 0.18, themeTag: 'JP' },
          ]},
          { id: 'bank', label: 'BANK', value: 0, children: [
            { id: 'jpm',  label: 'JPM',  value: 0.6 },
            { id: 'bac',  label: 'BAC',  value: 0.32 },
            { id: 'gs',   label: 'GS',   value: 0.18 },
            { id: '8306', label: '8306', value: 0.16 },
            { id: 'hsbc', label: 'HSBC', value: 0.21 },
          ]},
          { id: 'mfg', label: 'MFG', value: 0, children: [
            { id: 'tsla', label: 'TSLA', value: 1.1 },
            { id: '7203', label: '7203', value: 0.42 },
            { id: 'ge',   label: 'GE',   value: 0.18 },
            { id: 'cat',  label: 'CAT',  value: 0.16 },
            { id: 'mc',   label: 'MC',   value: 0.12 },
          ]},
          { id: 'energy', label: 'ENERGY', value: 0, themeTag: 'OIL_CYCLE', children: [
            { id: 'xom',  label: 'XOM',  value: 0.55 },
            { id: 'cvx',  label: 'CVX',  value: 0.32 },
            { id: 'shel', label: 'SHEL', value: 0.21 },
          ]},
          { id: 'health', label: 'HEALTH', value: 0, children: [
            { id: 'unh',  label: 'UNH',  value: 0.42 },
            { id: 'lly',  label: 'LLY',  value: 0.68 },
            { id: 'jnj',  label: 'JNJ',  value: 0.38 },
          ]},
          { id: 'consumer', label: 'CONSUMER', value: 0, children: [
            { id: 'amzn', label: 'AMZN', value: 1.9 },
            { id: 'wmt',  label: 'WMT',  value: 0.6 },
            { id: 'nke',  label: 'NKE',  value: 0.14 },
          ]},
        ],
      },

      // ───────────── REIT ─────────────
      {
        id: 'reit', label: 'REIT', value: 0,
        children: [
          { id: 'us-reit', label: 'US REIT', value: 1.2 },
          { id: 'jp-reit', label: 'JP REIT', value: 0.18 },
          { id: 'eu-reit', label: 'EU REIT', value: 0.42 },
        ],
      },

      // ───────────── CRYPTO ─────────────
      {
        id: 'crypto', label: 'CRYPTO', value: 0, alert: true, themeTag: 'BTC_RUN',
        children: [
          { id: 'btc',     label: 'BTC',    value: 1.8 },
          { id: 'eth',     label: 'ETH',    value: 0.42 },
          { id: 'stable',  label: 'STABLE', value: 0.18 },
          { id: 'alt',     label: 'ALT',    value: 0.32 },
        ],
      },

      // ───────────── FX (held value, not stock) ─────────────
      {
        id: 'fx', label: 'FX', value: 0,
        children: [
          { id: 'usd-fx', label: 'USD', value: 3.2 },
          { id: 'eur-fx', label: 'EUR', value: 1.2 },
          { id: 'jpy-fx', label: 'JPY', value: 0.8 },
          { id: 'cny-fx', label: 'CNY', value: 1.8 },
        ],
      },
    ],
  };
}

/**
 * Perturb leaf values while conserving the global total.
 * Models money sloshing between asset classes / sub-sectors / instruments.
 */
export function breatheAssets(tree: AssetTree): AssetTree {
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
    const noise = (Math.random() - 0.5) * 0.05; // ±2.5 %
    return { ...l, value: Math.max(0.04, l.value * (1 + noise)) };
  });
  const sum = perturbed.reduce((s, l) => s + l.value, 0);
  const scale = originalTotal / sum;
  const valById = new Map(perturbed.map((p) => [p.id, +(p.value * scale).toFixed(3)]));

  const rebuild = <T extends AssetNode | AssetTree>(n: T): T => {
    if ('children' in n && n.children && n.children.length) {
      return { ...n, children: n.children.map(rebuild) } as T;
    }
    const v = valById.get((n as AssetNode).id);
    return { ...n, value: v ?? (n as AssetNode).value } as T;
  };
  return rebuild(tree);
}
