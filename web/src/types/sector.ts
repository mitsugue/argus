/**
 * A.R.G.U.S. — sector liquidity network types.
 *
 * Nodes represent layers of the macro → sector → stock hierarchy. The PoC
 * renders only the `sector` depth; child depths are kept in the data
 * structure so the future semantic-zoom can drill in without restructuring.
 */

export type NodeDepth = 'macro' | 'sector' | 'stock';

export type AlertLevel = 'normal' | 'warm' | 'alert';

export interface SectorNode {
  id: string;
  label: string;
  depth: NodeDepth;
  /** Parent macro / sector id (null for top-level macros). */
  parentId: string | null;
  /** Mock liquidity in some abstract unit — drives node size. */
  liquidity: number;
  /** Direction of flow over the rolling window: -1..1, drives subtle color shift. */
  flow: number;
  alert: AlertLevel;
  /** Optional theme tag — e.g. "COPPER_SUPERCYCLE", surfaced in tooltip. */
  themeTag?: string;
}

export interface SectorLink {
  source: string;
  target: string;
  /** Strength of the relationship — pulled into d3-force's link strength. */
  weight: number;
}

export interface NetworkSnapshot {
  nodes: SectorNode[];
  links: SectorLink[];
  /** Total liquidity across all sectors — invariant we sum into. */
  totalLiquidity: number;
}
