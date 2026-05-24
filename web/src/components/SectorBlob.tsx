import React, { useEffect, useMemo, useRef, useState } from 'react';
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

// Pinch / zoom thresholds — cross these on release and we drill / pop.
const DRILL_SCALE = 1.55;
const POP_SCALE = 0.7;
const MIN_SCALE = 0.45;
const MAX_SCALE = 3.2;

export const SectorBlob: React.FC = () => {
  const [tree, setTree] = useState<AssetTree>(() => seedAssets());
  // focusPath is the chain from root to the currently focused subtree.
  // Always starts with 'root'. Tap a bubble → push its id. Back → pop.
  const [focusPath, setFocusPath] = useState<string[]>(['root']);

  // Live pinch scale + origin in SVG coords (0..PACK). Used for both visual
  // feedback during the gesture and to decide which bubble to drill into.
  const [scale, setScale] = useState(1);
  const [origin, setOrigin] = useState<{ x: number; y: number }>({ x: PACK / 2, y: PACK / 2 });
  const svgRef = useRef<SVGSVGElement>(null);
  const pinchRef = useRef<{
    startDist: number;
    startScale: number;
    clientCx: number;
    clientCy: number;
  } | null>(null);

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

  // Reset zoom whenever the focus changes — start the next level at 1×.
  useEffect(() => {
    setScale(1);
    setOrigin({ x: PACK / 2, y: PACK / 2 });
  }, [focusPath]);

  const handleClick = (n: AssetNode) => {
    if (n.children && n.children.length > 0) {
      setFocusPath((p) => [...p, n.id]);
    }
  };

  const popBack = () => setFocusPath((p) => (p.length > 1 ? p.slice(0, -1) : p));

  // ── Pinch / wheel — flexible zoom + drill gesture ───────────────────────
  const clientToSvg = (clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: PACK / 2, y: PACK / 2 };
    const rect = svg.getBoundingClientRect();
    // viewBox is square (0..PACK); preserveAspectRatio="meet" letterboxes.
    const side = Math.min(rect.width, rect.height);
    const offX = (rect.width - side) / 2;
    const offY = (rect.height - side) / 2;
    return {
      x: ((clientX - rect.left - offX) / side) * PACK,
      y: ((clientY - rect.top - offY) / side) * PACK,
    };
  };

  const bubbleAt = (sx: number, sy: number): PackNode | null => {
    // Pick the smallest (= deepest) containing bubble — feels right under finger.
    let best: PackNode | null = null;
    for (const n of nodes) {
      if (Math.hypot(sx - n.x, sy - n.y) <= n.r) {
        if (!best || n.r < best.r) best = n;
      }
    }
    return best;
  };

  const settleAfterGesture = (finalScale: number, svgCx: number, svgCy: number) => {
    if (finalScale >= DRILL_SCALE) {
      const hit = bubbleAt(svgCx, svgCy);
      const d = hit?.data as AssetNode | undefined;
      if (d?.children?.length) {
        setFocusPath((p) => [...p, d.id]);
        return;
      }
    } else if (finalScale <= POP_SCALE && focusPath.length > 1) {
      popBack();
      return;
    }
    // No threshold crossed → snap back smoothly.
    setScale(1);
    setOrigin({ x: PACK / 2, y: PACK / 2 });
  };

  const handleTouchStart = (e: React.TouchEvent<SVGSVGElement>) => {
    if (e.touches.length === 2) {
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      const dist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
      const clientCx = (t1.clientX + t2.clientX) / 2;
      const clientCy = (t1.clientY + t2.clientY) / 2;
      pinchRef.current = { startDist: dist, startScale: scale, clientCx, clientCy };
      const svgPt = clientToSvg(clientCx, clientCy);
      setOrigin(svgPt);
    }
  };

  const handleTouchMove = (e: React.TouchEvent<SVGSVGElement>) => {
    if (e.touches.length === 2 && pinchRef.current) {
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      const dist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
      const next = pinchRef.current.startScale * (dist / pinchRef.current.startDist);
      setScale(Math.max(MIN_SCALE, Math.min(MAX_SCALE, next)));
    }
  };

  const handleTouchEnd = (e: React.TouchEvent<SVGSVGElement>) => {
    if (!pinchRef.current) return;
    if (e.touches.length < 2) {
      const { clientCx, clientCy } = pinchRef.current;
      const svgPt = clientToSvg(clientCx, clientCy);
      const finalScale = scale;
      pinchRef.current = null;
      settleAfterGesture(finalScale, svgPt.x, svgPt.y);
    }
  };

  // Trackpad pinch (and ctrl+wheel) on desktop. Threshold-on-release uses a
  // short idle timer so we don't drill mid-pinch.
  const wheelSettleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    const svgPt = clientToSvg(e.clientX, e.clientY);
    setOrigin(svgPt);
    setScale((s) => {
      const next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, s - e.deltaY * 0.01));
      if (wheelSettleRef.current) clearTimeout(wheelSettleRef.current);
      wheelSettleRef.current = setTimeout(() => {
        settleAfterGesture(next, svgPt.x, svgPt.y);
      }, 220);
      return next;
    });
  };

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
        ref={svgRef}
        className="blob__svg"
        viewBox={`0 0 ${PACK} ${PACK}`}
        preserveAspectRatio="xMidYMid meet"
        xmlns="http://www.w3.org/2000/svg"
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onTouchCancel={handleTouchEnd}
        onWheel={handleWheel}
        style={{ touchAction: 'none' }}
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

        {/* Zoom wrapper — scaled about pinch center for live gesture feedback.
            Built via SVG transform attribute so it nests cleanly with the
            metaball filter and framer-motion circle animations. */}
        <g
          transform={`translate(${origin.x} ${origin.y}) scale(${scale}) translate(${-origin.x} ${-origin.y})`}
          style={{
            transition: pinchRef.current ? 'none' : 'transform 0.45s var(--hud-ease, ease-out)',
          }}
        >

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
        </g>
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
