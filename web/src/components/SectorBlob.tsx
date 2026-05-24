import React, { useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { hierarchy, pack, type HierarchyCircularNode } from 'd3-hierarchy';
import type { AssetNode, AssetTree } from '../types/asset';
import { breatheAssets, seedAssets } from '../mock/assets';
import './SectorBlob.css';

// ─────────────────────────────────────────────────────────────────────────
// Layout — d3.pack on the focused subtree
// ─────────────────────────────────────────────────────────────────────────

type PackNode = HierarchyCircularNode<AssetNode | AssetTree>;
type AnyNode = AssetNode | AssetTree;

const PACK = 100;

function findById(n: AnyNode, id: string): AnyNode | null {
  if ('id' in n && n.id === id) return n;
  const kids = (n as AssetNode).children;
  if (!kids) return null;
  for (const k of kids) {
    const hit = findById(k, id);
    if (hit) return hit;
  }
  return null;
}

function packChildren(subtreeRoot: AnyNode): PackNode[] {
  const root = hierarchy<AnyNode>(subtreeRoot)
    .sum((d) => {
      const c = (d as AssetNode).children;
      return c && c.length ? 0 : (d as AssetNode).value;
    })
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));

  const layout = pack<AnyNode>().size([PACK, PACK]).padding(1.1);
  const laidOut = layout(root);
  return (laidOut.children ?? []) as PackNode[];
}

// ─────────────────────────────────────────────────────────────────────────
// Color — single deep-ocean tone, density varies by depth in the path
// ─────────────────────────────────────────────────────────────────────────

const BUBBLE_TONES = [
  '#3a536d', // depth 1 — shallowest visible
  '#2b425d', // depth 2
  '#21354e', // depth 3
  '#192a40', // depth 4
];
const BUBBLE_ALERT = '#6a8aa0'; // moonlight pale — anomaly only

function bubbleFill(depth: number): string {
  return BUBBLE_TONES[Math.min(depth - 1, BUBBLE_TONES.length - 1)] ?? BUBBLE_TONES[0];
}

// ─────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────

export const SectorBlob: React.FC = () => {
  const [tree, setTree] = useState<AssetTree>(() => seedAssets());
  // focusPath is the chain from root to the currently focused subtree.
  // Always starts with 'root'. Tap a bubble → push its id. Back → pop.
  const [focusPath, setFocusPath] = useState<string[]>(['root']);

  // Breathe — perturb leaves every 2.4s. Slow enough to feel meditative.
  useEffect(() => {
    const t = setInterval(() => setTree((p) => breatheAssets(p)), 2400);
    return () => clearInterval(t);
  }, []);

  // Resolve the currently focused subtree and its packed children
  const { focused, nodes, depth } = useMemo(() => {
    const currentId = focusPath[focusPath.length - 1];
    const focused = currentId === 'root' ? tree : (findById(tree, currentId) as AnyNode);
    const nodes = packChildren(focused);
    return { focused, nodes, depth: focusPath.length };
  }, [tree, focusPath]);

  const handleClick = (n: AssetNode) => {
    if (n.children && n.children.length > 0) {
      setFocusPath((p) => [...p, n.id]);
    }
  };

  const popBack = () => setFocusPath((p) => (p.length > 1 ? p.slice(0, -1) : p));

  // Build the breadcrumb labels lazily — walk focusPath and resolve each
  const crumbs = useMemo(() => {
    const out: { id: string; label: string }[] = [{ id: 'root', label: 'WORLD' }];
    let cur: AnyNode = tree;
    for (let i = 1; i < focusPath.length; i++) {
      const next = findById(cur, focusPath[i]) as AssetNode | null;
      if (!next) break;
      out.push({ id: next.id, label: next.label });
      cur = next;
    }
    return out;
  }, [tree, focusPath]);

  return (
    <section className="blob">
      <svg
        className="blob__svg"
        viewBox={`0 0 ${PACK} ${PACK}`}
        preserveAspectRatio="xMidYMid meet"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          {/* Metaball filter — soft Gaussian blur + alpha threshold.
              Adjacent bubbles fuse into one organic mass; the threshold
              keeps each bubble's edge crisp where it's alone. */}
          <filter id="meta" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="2.2" result="b" />
            <feColorMatrix
              in="b"
              type="matrix"
              values="
                1 0 0 0  0
                0 1 0 0  0
                0 0 1 0  0
                0 0 0 18 -8"
            />
          </filter>
        </defs>

        {/* Fused bubble layer — flat matte fill, no gradient / no highlight */}
        <g filter="url(#meta)">
          <AnimatePresence mode="popLayout">
            {nodes.map((n) => {
              const d = n.data as AssetNode;
              const fill = d.alert ? BUBBLE_ALERT : bubbleFill(depth);
              return (
                <motion.circle
                  key={focusPath.join('/') + ':' + d.id}
                  initial={{ cx: PACK / 2, cy: PACK / 2, r: 0, opacity: 0 }}
                  animate={{ cx: n.x, cy: n.y, r: n.r, opacity: 1 }}
                  exit={{ r: 0, opacity: 0 }}
                  transition={{
                    type: 'spring',
                    stiffness: 60,
                    damping: 18,
                  }}
                  fill={fill}
                />
              );
            })}
          </AnimatePresence>
        </g>

        {/* Crisp overlay — minimal labels + click hit-targets.
            NOT under the metaball filter so text stays sharp. */}
        <AnimatePresence>
          {nodes.map((n) => {
            const d = n.data as AssetNode;
            const showLabel = n.r > 7;
            const labelSize = Math.max(2.2, Math.min(4.5, n.r * 0.3));
            return (
              <motion.g
                key={focusPath.join('/') + ':o:' + d.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.45 }}
                onClick={() => handleClick(d)}
                style={{ cursor: d.children?.length ? 'pointer' : 'default' }}
              >
                {/* Invisible hit circle — generous tap target */}
                <motion.circle
                  animate={{ cx: n.x, cy: n.y, r: n.r }}
                  transition={{ type: 'spring', stiffness: 60, damping: 18 }}
                  fill="rgba(0,0,0,0)"
                />
                {showLabel && (
                  <text
                    x={n.x}
                    y={n.y}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize={labelSize}
                    fontFamily="'JetBrains Mono', monospace"
                    fontWeight={500}
                    fill="rgba(220, 228, 236, 0.88)"
                    style={{ letterSpacing: '0.14em', pointerEvents: 'none' }}
                  >
                    {d.label}
                  </text>
                )}
              </motion.g>
            );
          })}
        </AnimatePresence>
      </svg>

      {/* Breadcrumb — only the back affordance; depth shown as dots */}
      <nav className="blob__crumbs" aria-label="depth path">
        {crumbs.map((c, i) => (
          <React.Fragment key={c.id}>
            <button
              className={`blob__crumb${i === crumbs.length - 1 ? ' is-current' : ''}`}
              onClick={() => setFocusPath(focusPath.slice(0, i + 1))}
              disabled={i === crumbs.length - 1}
            >
              {c.label}
            </button>
            {i < crumbs.length - 1 && <span className="blob__crumb-sep">/</span>}
          </React.Fragment>
        ))}
      </nav>

      {focusPath.length > 1 && (
        <button className="blob__back" onClick={popBack} aria-label="step back">
          ←
        </button>
      )}
    </section>
  );
};
