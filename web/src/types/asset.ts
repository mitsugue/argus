/**
 * A.R.G.U.S. v7 — hierarchical asset-class tree.
 *
 * Root → asset classes → (optional) sub-sectors.
 * Bubble sizes are computed by d3-hierarchy.pack() from `value` at the leaves.
 * Parents' visible size = sum of their children, so STOCK is naturally the
 * biggest bubble because it contains many sub-sector children.
 */

export type AssetId = string;

export interface AssetNode {
  id: AssetId;
  label: string;
  /** Liquidity in arbitrary mock units. Drives bubble size via d3.pack. */
  value: number;
  /** Optional theme tag — surfaced in tooltip. */
  themeTag?: string;
  /** Whether this node is currently flagged as anomalous. */
  alert?: boolean;
  /** Performance heat: -1..1 (red ↔ green). Tints the bubble. */
  heat?: number;
  children?: AssetNode[];
}

export interface AssetTree {
  id: 'root';
  /** Always 0 — pack uses the sum of children. */
  value: 0;
  children: AssetNode[];
}
