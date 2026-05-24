import React, { useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { hierarchy, pack, type HierarchyCircularNode } from 'd3-hierarchy';
import type { AssetNode, AssetTree } from '../types/asset';
import { breatheAssets, seedAssets } from '../mock/assets';
import './SectorBlob.css';

// ─────────────────────────────────────────────────────────────────────────
// Layout helpers
// ─────────────────────────────────────────────────────────────────────────

type PackNode = HierarchyCircularNode<AssetNode | AssetTree>;

const PACK_W = 100;
const PACK_H = 100;

/**
 * Run d3.pack over the subtree rooted at `focusId` (or the global tree if
 * focus is null). Returns the leaf-level packed circles ready to render.
 */
function computePack(
  tree: AssetTree | AssetNode,
  focusId: string | null,
): { nodes: PackNode[]; root: PackNode | null } {
  // Resolve focus subtree
  let subtreeRoot: AssetTree | AssetNode = tree;
  if (focusId) {
    const find = (n: AssetTree | AssetNode): AssetNode | null => {
      if ('id' in n && n.id === focusId) return n as AssetNode;
      const kids = (n as AssetNode).children;
      if (!kids) return null;
      for (const k of kids) {
        const hit = find(k);
        if (hit) return hit;
      }
      return null;
    };
    const focused = find(tree);
    if (focused) subtreeRoot = focused;
  }

  const root = hierarchy<AssetNode | AssetTree>(subtreeRoot)
    .sum((d) => {
      // Sum at leaves only (parents inherit). For focused subtree, even the
      // root has its own children's value.
      if ('children' in d && d.children && d.children.length) return 0;
      return d.value;
    })
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));

  const layout = pack<AssetNode | AssetTree>()
    .size([PACK_W, PACK_H])
    .padding((d) => (d.depth === 0 ? 1 : 2));

  const laidOut = layout(root);

  // We render the IMMEDIATE children of the displayed root as the bubble
  // cluster — these are the visible asset classes (or sub-sectors when
  // drilled in). After layout(), children gain x/y/r.
  const nodes: PackNode[] = (laidOut.children ?? []) as PackNode[];
  return { nodes, root: laidOut };
}

// ─────────────────────────────────────────────────────────────────────────
// Color mapping — light-blue base, heat tints toward green / red
// ─────────────────────────────────────────────────────────────────────────

const BLUE_DEEP = [70, 130, 175] as const;   // #4682af — base for the bubble core
const GREEN_TINT = [80, 165, 100] as const;
const RED_TINT = [200, 70, 70] as const;

function mix(a: readonly number[], b: readonly number[], t: number): string {
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

function bubbleColor(node: AssetNode): { core: string; rim: string; glow: string } {
  const heat = Math.max(-1, Math.min(1, node.heat ?? 0));
  let core: string;
  let glow: string;
  if (heat >= 0) {
    core = mix(BLUE_DEEP, GREEN_TINT, heat * 0.6);
    glow = mix([180, 215, 235], GREEN_TINT, heat * 0.4);
  } else {
    core = mix(BLUE_DEEP, RED_TINT, -heat * 0.6);
    glow = mix([180, 215, 235], RED_TINT, -heat * 0.4);
  }
  const rim = node.alert ? 'rgba(200, 60, 70, 0.85)' : 'rgba(40, 80, 120, 0.4)';
  return { core, rim, glow };
}

// ─────────────────────────────────────────────────────────────────────────
// Main blob cluster
// ─────────────────────────────────────────────────────────────────────────

export const SectorBlob: React.FC = () => {
  const [tree, setTree] = useState<AssetTree>(() => seedAssets());
  const [focusId, setFocusId] = useState<string | null>(null);

  // Breathe — perturb leaves every 2 s
  useEffect(() => {
    const t = setInterval(() => setTree((p) => breatheAssets(p)), 2000);
    return () => clearInterval(t);
  }, []);

  const { nodes } = useMemo(() => computePack(tree, focusId), [tree, focusId]);

  // Find focused node for back-button label
  const focusedNode = useMemo<AssetNode | null>(() => {
    if (!focusId) return null;
    const walk = (n: AssetTree | AssetNode): AssetNode | null => {
      if ('id' in n && n.id === focusId) return n as AssetNode;
      const kids = (n as AssetNode).children;
      if (!kids) return null;
      for (const k of kids) {
        const h = walk(k);
        if (h) return h;
      }
      return null;
    };
    return walk(tree);
  }, [focusId, tree]);

  const handleBubbleClick = (n: AssetNode) => {
    if (n.children && n.children.length > 0) {
      setFocusId(n.id);
    }
  };

  return (
    <section className="blob">
      <svg
        className="blob__svg"
        viewBox={`0 0 ${PACK_W} ${PACK_H}`}
        preserveAspectRatio="xMidYMid meet"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          {/* Metaball filter — high blur + alpha threshold so adjacent
              circles fuse into one organic shape with smooth necks. */}
          <filter id="metaball" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="1.6" result="blur" />
            <feColorMatrix
              in="blur"
              type="matrix"
              values="
                1 0 0 0  0
                0 1 0 0  0
                0 0 1 0  0
                0 0 0 22 -10"
              result="goo"
            />
            <feComposite in="SourceGraphic" in2="goo" operator="atop" />
          </filter>

          {/* Per-bubble radial gradients are generated inline below.
              We also pre-declare a generic highlight gradient. */}
          <radialGradient id="bubble-highlight" cx="35%" cy="30%" r="50%">
            <stop offset="0%" stopColor="rgba(255, 255, 255, 0.6)" />
            <stop offset="60%" stopColor="rgba(255, 255, 255, 0)" />
          </radialGradient>
        </defs>

        {/* Fused blob layer — metaball-filtered circles produce the soft
            connecting necks between adjacent bubbles, like the reference. */}
        <g filter="url(#metaball)">
          <AnimatePresence>
            {nodes.map((n) => {
              const d = n.data as AssetNode;
              const c = bubbleColor(d);
              return (
                <motion.circle
                  key={d.id}
                  initial={{ cx: PACK_W / 2, cy: PACK_H / 2, r: 0 }}
                  animate={{ cx: n.x, cy: n.y, r: n.r }}
                  exit={{ r: 0, opacity: 0 }}
                  transition={{ type: 'spring', stiffness: 70, damping: 16 }}
                  fill={c.core}
                />
              );
            })}
          </AnimatePresence>
        </g>

        {/* Highlight + label overlay (sharp, NOT going through the metaball
            filter) — preserves crisp text and the glassy specular spot. */}
        <AnimatePresence>
          {nodes.map((n) => {
            const d = n.data as AssetNode;
            const c = bubbleColor(d);
            const showLabel = n.r > 6;
            return (
              <motion.g
                key={d.id + ':overlay'}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.4 }}
                onClick={() => handleBubbleClick(d)}
                style={{ cursor: d.children?.length ? 'pointer' : 'default' }}
              >
                <motion.ellipse
                  animate={{ cx: n.x - n.r * 0.25, cy: n.y - n.r * 0.35, rx: n.r * 0.45, ry: n.r * 0.28 }}
                  transition={{ type: 'spring', stiffness: 70, damping: 16 }}
                  fill="url(#bubble-highlight)"
                  pointerEvents="none"
                />
                {d.alert && (
                  <motion.circle
                    animate={{ cx: n.x, cy: n.y, r: n.r * 0.98 }}
                    transition={{ type: 'spring', stiffness: 70, damping: 16 }}
                    fill="none"
                    stroke={c.rim}
                    strokeWidth={0.4}
                    pointerEvents="none"
                  />
                )}
                {showLabel && (
                  <motion.text
                    animate={{ x: n.x, y: n.y + 0.6 }}
                    transition={{ type: 'spring', stiffness: 70, damping: 16 }}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize={Math.max(2.2, Math.min(5.5, n.r * 0.38))}
                    fontFamily="'JetBrains Mono', monospace"
                    fontWeight={600}
                    fill="rgba(255, 255, 255, 0.95)"
                    style={{
                      letterSpacing: '0.1em',
                      pointerEvents: 'none',
                      textShadow: '0 1px 2px rgba(20, 50, 80, 0.4)',
                    }}
                  >
                    {d.label}
                  </motion.text>
                )}
              </motion.g>
            );
          })}
        </AnimatePresence>
      </svg>

      {focusedNode && (
        <button className="blob__back" onClick={() => setFocusId(null)} aria-label="back to global view">
          ← {focusedNode.label}
        </button>
      )}
    </section>
  );
};
