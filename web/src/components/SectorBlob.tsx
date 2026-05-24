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
const INITIAL_SCALE = 1.5; // start zoomed in so the mass dominates the viewport

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

  const layout = pack<AnyNode>().size([PACK, PACK]).padding(1.2);
  const laidOut = layout(root);
  return (laidOut.children ?? []) as PackNode[];
}

// ─────────────────────────────────────────────────────────────────────────
// Color — single deep-ocean tone, density varies by depth
// ─────────────────────────────────────────────────────────────────────────

const BUBBLE_TONES = [
  '#3a536d', // depth 1
  '#2b425d', // depth 2
  '#21354e', // depth 3
  '#192a40', // depth 4
];
const BUBBLE_ALERT = '#6a8aa0';

function bubbleFill(depth: number): string {
  return BUBBLE_TONES[Math.min(depth - 1, BUBBLE_TONES.length - 1)] ?? BUBBLE_TONES[0];
}

// ─────────────────────────────────────────────────────────────────────────
// Gesture thresholds — relative to the scale at which the gesture started
// ─────────────────────────────────────────────────────────────────────────

const DRILL_RATIO = 1.55; // pinch out by ≥55% from start → drill in
const POP_RATIO = 0.65;   // pinch in to ≤65% of start → pop back
const MIN_SCALE = 0.45;
const MAX_SCALE = 4.5;

// ─────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────

export const SectorBlob: React.FC = () => {
  const [tree, setTree] = useState<AssetTree>(() => seedAssets());
  const [focusPath, setFocusPath] = useState<string[]>(['root']);

  // Live transform — scale around `origin`, plus free `pan` translation
  const [scale, setScale] = useState(INITIAL_SCALE);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [origin, setOrigin] = useState({ x: PACK / 2, y: PACK / 2 });
  const [activeGesture, setActiveGesture] = useState<null | 'drag' | 'pinch'>(null);

  const svgRef = useRef<SVGSVGElement>(null);
  const turbRef = useRef<SVGFETurbulenceElement>(null);
  const pinchRef = useRef<{
    startDist: number;
    startScale: number;
    clientCx: number;
    clientCy: number;
  } | null>(null);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    startPan: { x: number; y: number };
  } | null>(null);

  // Breathe — perturb leaves slowly. Viscous tempo, not nervous.
  useEffect(() => {
    const t = setInterval(() => setTree((p) => breatheAssets(p)), 3600);
    return () => clearInterval(t);
  }, []);

  // Slow morph the displacement-map turbulence — keeps the edges alive.
  // Mutate the DOM attribute directly so React isn't re-rendered at 60fps.
  useEffect(() => {
    let raf = 0;
    let last = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      if (now - last > 60) {
        last = now;
        const node = turbRef.current;
        if (node) {
          const t = (now - t0) / 1000;
          const fx = 0.022 + Math.sin(t * 0.23) * 0.006;
          const fy = 0.024 + Math.cos(t * 0.19) * 0.005;
          node.setAttribute('baseFrequency', `${fx} ${fy}`);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Resolve the currently focused subtree and its packed children
  const { nodes, depth } = useMemo(() => {
    const currentId = focusPath[focusPath.length - 1];
    const focused = currentId === 'root' ? tree : (findById(tree, currentId) as AnyNode);
    const packed = packChildren(focused);
    return { nodes: packed, depth: focusPath.length };
  }, [tree, focusPath]);

  // Reset to a clean view on any focus change.
  useEffect(() => {
    setScale(INITIAL_SCALE);
    setPan({ x: 0, y: 0 });
    setOrigin({ x: PACK / 2, y: PACK / 2 });
  }, [focusPath]);

  const handleClick = (n: AssetNode) => {
    if (n.children && n.children.length > 0) {
      setFocusPath((p) => [...p, n.id]);
    }
  };

  const popBack = () => setFocusPath((p) => (p.length > 1 ? p.slice(0, -1) : p));

  // ── Coordinate helpers ────────────────────────────────────────────────
  const clientToSvg = (clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: PACK / 2, y: PACK / 2 };
    const rect = svg.getBoundingClientRect();
    const side = Math.min(rect.width, rect.height);
    const offX = (rect.width - side) / 2;
    const offY = (rect.height - side) / 2;
    return {
      x: ((clientX - rect.left - offX) / side) * PACK,
      y: ((clientY - rect.top - offY) / side) * PACK,
    };
  };

  const bubbleAt = (sx: number, sy: number): PackNode | null => {
    let best: PackNode | null = null;
    for (const n of nodes) {
      if (Math.hypot(sx - n.x, sy - n.y) <= n.r) {
        if (!best || n.r < best.r) best = n;
      }
    }
    return best;
  };

  const settleAfterGesture = (
    finalScale: number,
    startScale: number,
    svgCx: number,
    svgCy: number
  ) => {
    const ratio = finalScale / startScale;
    if (ratio >= DRILL_RATIO) {
      const hit = bubbleAt(svgCx, svgCy);
      const d = hit?.data as AssetNode | undefined;
      if (d?.children?.length) {
        setFocusPath((p) => [...p, d.id]);
        return;
      }
    } else if (ratio <= POP_RATIO && focusPath.length > 1) {
      popBack();
    }
    // No threshold crossed → leave scale + pan where the user left them.
  };

  // ── Pinch (2-finger touch) ────────────────────────────────────────────
  const handleTouchStart = (e: React.TouchEvent<SVGSVGElement>) => {
    if (e.touches.length === 2) {
      // 2nd finger lands → cancel any in-progress single-finger drag
      if (dragRef.current) dragRef.current = null;
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      const dist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
      const clientCx = (t1.clientX + t2.clientX) / 2;
      const clientCy = (t1.clientY + t2.clientY) / 2;
      pinchRef.current = { startDist: dist, startScale: scale, clientCx, clientCy };
      setOrigin(clientToSvg(clientCx, clientCy));
      setActiveGesture('pinch');
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
      const { clientCx, clientCy, startScale } = pinchRef.current;
      const svgPt = clientToSvg(clientCx, clientCy);
      const finalScale = scale;
      pinchRef.current = null;
      setActiveGesture(null);
      settleAfterGesture(finalScale, startScale, svgPt.x, svgPt.y);
    }
  };

  // ── Drag pan (single pointer) ─────────────────────────────────────────
  const handlePointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (pinchRef.current) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startPan: pan,
    };
    setActiveGesture('drag');
    try {
      (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
    } catch {
      /* some browsers throw on already-captured */
    }
  };

  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!dragRef.current || pinchRef.current) return;
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const side = Math.min(rect.width, rect.height);
    // svg units per screen pixel — pan is applied AFTER scale in the
    // transform string, so 1 unit of pan = 1 viewBox unit visually, which
    // is `side / PACK` pixels on screen at scale = 1, scaled by `scale` otherwise.
    const f = PACK / side / scale;
    const dx = (e.clientX - dragRef.current.startX) * f;
    const dy = (e.clientY - dragRef.current.startY) * f;
    setPan({
      x: dragRef.current.startPan.x + dx,
      y: dragRef.current.startPan.y + dy,
    });
  };

  const handlePointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    setActiveGesture(null);
    try {
      (e.currentTarget as SVGSVGElement).releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  // ── Wheel — trackpad pinch / ctrl-wheel zoom ──────────────────────────
  const wheelSessionRef = useRef<{ startScale: number; lastAt: number } | null>(null);
  const wheelSettleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    const now = performance.now();
    if (!wheelSessionRef.current || now - wheelSessionRef.current.lastAt > 400) {
      wheelSessionRef.current = { startScale: scale, lastAt: now };
    } else {
      wheelSessionRef.current.lastAt = now;
    }
    const svgPt = clientToSvg(e.clientX, e.clientY);
    setOrigin(svgPt);
    setScale((s) => {
      const next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, s - e.deltaY * 0.005));
      if (wheelSettleRef.current) clearTimeout(wheelSettleRef.current);
      wheelSettleRef.current = setTimeout(() => {
        const startScale = wheelSessionRef.current?.startScale ?? next;
        wheelSessionRef.current = null;
        settleAfterGesture(next, startScale, svgPt.x, svgPt.y);
      }, 260);
      return next;
    });
  };

  // ── Breadcrumb ────────────────────────────────────────────────────────
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

  // Compose translate + scale-around-origin + pan in viewBox units.
  // Pan is applied OUTSIDE the scale so it tracks the finger 1:1 after we
  // divide by `scale` in pointermove.
  const wrapperTransform = `translate(${pan.x} ${pan.y}) translate(${origin.x} ${origin.y}) scale(${scale}) translate(${-origin.x} ${-origin.y})`;

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
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onWheel={handleWheel}
        style={{
          touchAction: 'none',
          cursor: activeGesture === 'drag' ? 'grabbing' : 'grab',
        }}
      >
        <defs>
          {/* Metaball + organic edge:
              1) Blur source → 2) alpha threshold so circles fuse into one mass
              3) Slow-morphing fractal-noise turbulence
              4) Displace step (2) by step (3) → wobbly, viscous-bubble outline. */}
          <filter id="meta" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="2.6" result="b" />
            <feColorMatrix
              in="b"
              type="matrix"
              values="
                1 0 0 0  0
                0 1 0 0  0
                0 0 1 0  0
                0 0 0 22 -10"
              result="m"
            />
            <feTurbulence
              ref={turbRef}
              type="fractalNoise"
              baseFrequency="0.022 0.024"
              numOctaves="2"
              seed="7"
              result="t"
            />
            <feDisplacementMap
              in="m"
              in2="t"
              scale="6"
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
        </defs>

        {/* Pan/zoom wrapper — instant tracking during a gesture, springy
            settling otherwise (ぷるん). */}
        <g
          transform={wrapperTransform}
          style={{
            transition: activeGesture
              ? 'none'
              : 'transform 0.55s cubic-bezier(0.34, 1.4, 0.5, 1)',
          }}
        >
          {/* Fused bubble layer */}
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
                      // Jelly spring — under-damped so the mass jiggles when
                      // it lands. Higher mass = slower, gummier settling.
                      type: 'spring',
                      stiffness: 55,
                      damping: 10,
                      mass: 1.4,
                    }}
                    fill={fill}
                  />
                );
              })}
            </AnimatePresence>
          </g>

          {/* Crisp overlay — labels + invisible hit targets. */}
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
                  transition={{ duration: 0.55 }}
                  onClick={() => handleClick(d)}
                  style={{ cursor: d.children?.length ? 'pointer' : 'default' }}
                >
                  <motion.circle
                    animate={{ cx: n.x, cy: n.y, r: n.r }}
                    transition={{ type: 'spring', stiffness: 55, damping: 10, mass: 1.4 }}
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

      {/* Breadcrumb */}
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
