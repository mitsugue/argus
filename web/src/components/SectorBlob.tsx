import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
const INITIAL_SCALE = 1.5;
const MIN_SCALE = 0.4;
const MAX_SCALE = 6;
const DRILL_RATIO = 1.55;
const POP_RATIO = 0.65;
const TAP_PX = 6;

// Spring config for the viewBox transitions on focus changes — ぷるん bounce.
const SPRING_K = 130;
const SPRING_C = 12;
const SPRING_M = 0.65;

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

const BUBBLE_TONES = ['#3a536d', '#2b425d', '#21354e', '#192a40'];
const BUBBLE_ALERT = '#6a8aa0';
function bubbleFill(depth: number): string {
  return BUBBLE_TONES[Math.min(depth - 1, BUBBLE_TONES.length - 1)] ?? BUBBLE_TONES[0];
}

// ─────────────────────────────────────────────────────────────────────────
// ViewBox helpers — zoom/pan via viewBox so the browser re-rasterizes the
// filter at native pixel density (= crisp at any zoom).
// ─────────────────────────────────────────────────────────────────────────

const defaultVb = () => {
  const w = PACK / INITIAL_SCALE;
  return { x: (PACK - w) / 2, y: (PACK - w) / 2, w };
};

// ─────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────

export const SectorBlob: React.FC = () => {
  const [tree, setTree] = useState<AssetTree>(() => seedAssets());
  const [focusPath, setFocusPath] = useState<string[]>(['root']);

  // The viewBox we *want* — live values spring toward this each frame.
  const [target, setTarget] = useState(defaultVb);
  const targetRef = useRef(target);
  useEffect(() => {
    targetRef.current = target;
  }, [target]);

  const [activeGesture, setActiveGesture] = useState<null | 'drag' | 'pinch'>(null);
  const activeGestureRef = useRef<null | 'drag' | 'pinch'>(null);
  activeGestureRef.current = activeGesture;

  const svgRef = useRef<SVGSVGElement>(null);
  const turbRef = useRef<SVGFETurbulenceElement>(null);
  const dispRef = useRef<SVGFEDisplacementMapElement>(null);
  const pinchRef = useRef<{
    startDist: number;
    startVb: { x: number; y: number; w: number };
    clientCx: number;
    clientCy: number;
  } | null>(null);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    startVbX: number;
    startVbY: number;
    upgraded: boolean;
  } | null>(null);

  // Asset values breathe in a viscous tempo
  useEffect(() => {
    const t = setInterval(() => setTree((p) => breatheAssets(p)), 3600);
    return () => clearInterval(t);
  }, []);

  // Continuous filter morph: shift the noise frequency AND pulse the
  // displacement amplitude. Mutates DOM directly — no React re-renders.
  // This keeps the bubble outlines alive during pan/zoom/idle.
  useEffect(() => {
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const t = (now - t0) / 1000;
      const tn = turbRef.current;
      if (tn) {
        const fx = 0.022 + Math.sin(t * 0.65) * 0.011;
        const fy = 0.025 + Math.cos(t * 0.48) * 0.010;
        tn.setAttribute('baseFrequency', `${fx} ${fy}`);
      }
      const dn = dispRef.current;
      if (dn) {
        const s = 5.5 + Math.sin(t * 0.9) * 1.8; // "sloshing" pulse
        dn.setAttribute('scale', `${s}`);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Spring loop: lives at 60fps. Snap to target during gestures (immediate
  // tracking), spring toward target otherwise (gummy ぷるん settle).
  // Writes the viewBox attribute directly — no React reconciliation churn.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const live = { ...targetRef.current, vx: 0, vy: 0, vw: 0 };
    const step = (val: number, vel: number, tgt: number, dt: number): [number, number] => {
      const dx = val - tgt;
      const a = (-SPRING_K * dx - SPRING_C * vel) / SPRING_M;
      const nv = vel + a * dt;
      return [val + nv * dt, nv];
    };
    const tick = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.033);
      last = now;
      const t = targetRef.current;
      if (activeGestureRef.current) {
        live.x = t.x;
        live.y = t.y;
        live.w = t.w;
        live.vx = live.vy = live.vw = 0;
      } else {
        [live.x, live.vx] = step(live.x, live.vx, t.x, dt);
        [live.y, live.vy] = step(live.y, live.vy, t.y, dt);
        [live.w, live.vw] = step(live.w, live.vw, t.w, dt);
      }
      svgRef.current?.setAttribute('viewBox', `${live.x} ${live.y} ${live.w} ${live.w}`);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Paint the initial viewBox synchronously so the first frame is correct.
  useLayoutEffect(() => {
    const vb = defaultVb();
    svgRef.current?.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.w}`);
  }, []);

  const { nodes, depth } = useMemo(() => {
    const currentId = focusPath[focusPath.length - 1];
    const focused = currentId === 'root' ? tree : (findById(tree, currentId) as AnyNode);
    const packed = packChildren(focused);
    return { nodes: packed, depth: focusPath.length };
  }, [tree, focusPath]);

  // On focus change, just retarget — the spring takes care of the motion.
  useEffect(() => {
    setTarget(defaultVb());
  }, [focusPath]);

  const popBack = () => setFocusPath((p) => (p.length > 1 ? p.slice(0, -1) : p));

  // ── Coord helpers ────────────────────────────────────────────────────
  const clientToSvg = (clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: PACK / 2, y: PACK / 2 };
    const rect = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const side = Math.min(rect.width, rect.height);
    const offX = (rect.width - side) / 2;
    const offY = (rect.height - side) / 2;
    return {
      x: vb.x + ((clientX - rect.left - offX) / side) * vb.width,
      y: vb.y + ((clientY - rect.top - offY) / side) * vb.height,
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

  const drillInto = (id: string) => setFocusPath((p) => [...p, id]);

  const settleAfterGesture = (
    finalScale: number,
    startScale: number,
    clientX: number,
    clientY: number
  ) => {
    const ratio = finalScale / startScale;
    if (ratio >= DRILL_RATIO) {
      const svgPt = clientToSvg(clientX, clientY);
      const hit = bubbleAt(svgPt.x, svgPt.y);
      const d = hit?.data as AssetNode | undefined;
      if (d?.children?.length) {
        drillInto(d.id);
        return;
      }
    } else if (ratio <= POP_RATIO && focusPath.length > 1) {
      popBack();
    }
  };

  // ── Pinch (2-finger touch) ───────────────────────────────────────────
  const handleTouchStart = (e: React.TouchEvent<SVGSVGElement>) => {
    if (e.touches.length === 2) {
      if (dragRef.current) dragRef.current = null;
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      const dist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
      const cx = (t1.clientX + t2.clientX) / 2;
      const cy = (t1.clientY + t2.clientY) / 2;
      pinchRef.current = {
        startDist: dist,
        startVb: { ...targetRef.current },
        clientCx: cx,
        clientCy: cy,
      };
      setActiveGesture('pinch');
    }
  };

  const handleTouchMove = (e: React.TouchEvent<SVGSVGElement>) => {
    if (e.touches.length === 2 && pinchRef.current) {
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      const dist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
      const ratio = dist / pinchRef.current.startDist;
      const { startVb, clientCx, clientCy } = pinchRef.current;
      const newW = Math.max(
        PACK / MAX_SCALE,
        Math.min(PACK / MIN_SCALE, startVb.w / ratio)
      );
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const side = Math.min(rect.width, rect.height);
      const offX = (rect.width - side) / 2;
      const offY = (rect.height - side) / 2;
      const px = (clientCx - rect.left - offX) / side;
      const py = (clientCy - rect.top - offY) / side;
      // Anchor the pinch midpoint — the source point under the fingers
      // stays at the same screen position throughout the gesture.
      setTarget({
        x: startVb.x + px * (startVb.w - newW),
        y: startVb.y + py * (startVb.w - newW),
        w: newW,
      });
    }
  };

  const handleTouchEnd = (e: React.TouchEvent<SVGSVGElement>) => {
    if (!pinchRef.current) return;
    if (e.touches.length < 2) {
      const startScale = PACK / pinchRef.current.startVb.w;
      const finalScale = PACK / targetRef.current.w;
      const { clientCx, clientCy } = pinchRef.current;
      pinchRef.current = null;
      setActiveGesture(null);
      settleAfterGesture(finalScale, startScale, clientCx, clientCy);
    }
  };

  // ── Pointer: tap-or-drag ─────────────────────────────────────────────
  // Don't capture on pointerdown — wait until the user moves past TAP_PX.
  // That preserves clicks: short, still pointerup → drill into the bubble.
  const handlePointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (pinchRef.current) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startVbX: targetRef.current.x,
      startVbY: targetRef.current.y,
      upgraded: false,
    };
  };

  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!dragRef.current || pinchRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    if (!dragRef.current.upgraded) {
      if (Math.hypot(dx, dy) < TAP_PX) return;
      dragRef.current.upgraded = true;
      setActiveGesture('drag');
      try {
        (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
      } catch {
        /* already captured */
      }
    }
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const side = Math.min(rect.width, rect.height);
    // source units per pixel — drag pulls the viewBox the OPPOSITE direction
    // of the finger so the content under the finger stays under the finger.
    const f = targetRef.current.w / side;
    setTarget((t) => ({
      ...t,
      x: dragRef.current!.startVbX - dx * f,
      y: dragRef.current!.startVbY - dy * f,
    }));
  };

  const handlePointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!dragRef.current) return;
    const wasDrag = dragRef.current.upgraded;
    const startX = dragRef.current.startX;
    const startY = dragRef.current.startY;
    dragRef.current = null;
    if (wasDrag) {
      setActiveGesture(null);
      try {
        (e.currentTarget as SVGSVGElement).releasePointerCapture(e.pointerId);
      } catch {
        /* not captured */
      }
    } else {
      // It was a tap — drill into whatever bubble sat under the cursor.
      const svgPt = clientToSvg(startX, startY);
      const hit = bubbleAt(svgPt.x, svgPt.y);
      const d = hit?.data as AssetNode | undefined;
      if (d?.children?.length) drillInto(d.id);
    }
  };

  // ── Wheel (ctrl/cmd → trackpad pinch, mouse wheel zoom) ──────────────
  const wheelSessionRef = useRef<{
    startW: number;
    lastAt: number;
    lastClientX: number;
    lastClientY: number;
  } | null>(null);
  const wheelSettleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    const now = performance.now();
    if (!wheelSessionRef.current || now - wheelSessionRef.current.lastAt > 400) {
      wheelSessionRef.current = {
        startW: targetRef.current.w,
        lastAt: now,
        lastClientX: e.clientX,
        lastClientY: e.clientY,
      };
    } else {
      wheelSessionRef.current.lastAt = now;
      wheelSessionRef.current.lastClientX = e.clientX;
      wheelSessionRef.current.lastClientY = e.clientY;
    }
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const side = Math.min(rect.width, rect.height);
    const offX = (rect.width - side) / 2;
    const offY = (rect.height - side) / 2;
    const px = (e.clientX - rect.left - offX) / side;
    const py = (e.clientY - rect.top - offY) / side;
    const factor = Math.exp(e.deltaY * 0.005);
    setTarget((t) => {
      const newW = Math.max(
        PACK / MAX_SCALE,
        Math.min(PACK / MIN_SCALE, t.w * factor)
      );
      return {
        x: t.x + px * (t.w - newW),
        y: t.y + py * (t.w - newW),
        w: newW,
      };
    });
    if (wheelSettleRef.current) clearTimeout(wheelSettleRef.current);
    wheelSettleRef.current = setTimeout(() => {
      const session = wheelSessionRef.current;
      if (!session) return;
      wheelSessionRef.current = null;
      const startScale = PACK / session.startW;
      const finalScale = PACK / targetRef.current.w;
      settleAfterGesture(finalScale, startScale, session.lastClientX, session.lastClientY);
    }, 260);
  };

  // ── Breadcrumb ───────────────────────────────────────────────────────
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
        /* Constant initial viewBox — useLayoutEffect overrides immediately,
           then the rAF spring owns the attribute. React won't reset it
           because the JSX value never changes. */
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
              1) Blur + alpha threshold → adjacent circles fuse into one mass
              2) Slow-morphing fractal-noise turbulence
              3) Displace the fused mass by the noise → wobbly viscous edge */}
          <filter id="meta" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="2.4" result="b" />
            <feColorMatrix
              in="b"
              type="matrix"
              values="
                1 0 0 0  0
                0 1 0 0  0
                0 0 1 0  0
                0 0 0 26 -12"
              result="m"
            />
            <feTurbulence
              ref={turbRef}
              type="fractalNoise"
              baseFrequency="0.022 0.025"
              numOctaves="2"
              seed="7"
              result="t"
            />
            <feDisplacementMap
              ref={dispRef}
              in="m"
              in2="t"
              scale="5.5"
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
        </defs>

        {/* Fused bubble layer — circles in source space, no wrapper transform */}
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

        {/* Crisp labels — not filtered, always sharp */}
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
                style={{ pointerEvents: 'none' }}
              >
                {showLabel && (
                  <text
                    x={n.x}
                    y={n.y}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize={labelSize}
                    fontFamily="'JetBrains Mono', monospace"
                    fontWeight={300}
                    fill="rgba(220, 228, 236, 0.86)"
                    style={{ letterSpacing: '0.2em' }}
                  >
                    {d.label}
                  </text>
                )}
              </motion.g>
            );
          })}
        </AnimatePresence>
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
