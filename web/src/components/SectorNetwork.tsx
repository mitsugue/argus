import React, { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph3D, { type ForceGraphMethods } from 'react-force-graph-3d';
import * as THREE from 'three';
import type { NetworkSnapshot, SectorNode } from '../types/sector';
import { breatheNetwork, seedNetwork } from '../mock/sectors';
import './SectorNetwork.css';

const ALERT_COLOR = '#ff3d4f';

/** Liquidity (~100..2000) → bubble radius in scene units. */
function radiusFor(liquidity: number): number {
  return 5 + Math.sqrt(liquidity) * 0.65;
}

/** Whether this node is currently in an alarming state. */
function isAlerting(n: SectorNode): boolean {
  return n.alert === 'alert';
}

/** Per-node display color — alert overrides, otherwise sector palette. */
function nodeColor(n: SectorNode): string {
  return isAlerting(n) ? ALERT_COLOR : n.color;
}

/** Build a sprite label from canvas-rendered text. Sized in scene units. */
function makeLabelSprite(text: string, fillColor: string): THREE.Sprite {
  const W = 512;
  const H = 128;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, W, H);

  // Faint dark glow halo so text reads against light bg
  ctx.shadowColor = 'rgba(0, 0, 0, 0.35)';
  ctx.shadowBlur = 10;
  ctx.font = '600 56px "JetBrains Mono", "SFMono-Regular", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = fillColor;
  ctx.fillText(text, W / 2, H / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  texture.anisotropy = 4;

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false, // labels always render on top of bubbles
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(material);
  // Sprite world-space size — much larger so the label is legible against
  // the bubble at the typical camera distance the force layout produces.
  sprite.scale.set(60, 15, 1);
  return sprite;
}

export const SectorNetwork: React.FC = () => {
  const [snap, setSnap] = useState<NetworkSnapshot>(() => seedNetwork());
  const [size, setSize] = useState({ w: 0, h: 0 });
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);

  // Container size tracking
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setSize({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // Breathe — perturb liquidity every 1.2s
  useEffect(() => {
    const t = setInterval(() => {
      setSnap((prev) => breatheNetwork(prev));
    }, 1200);
    return () => clearInterval(t);
  }, []);

  // Add ambient lighting for any MeshLambert/Phong materials in the scene.
  // The bubble bodies themselves use MeshBasicMaterial so they don't need
  // lights — this is just for future depth.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || size.w === 0) return;
    const scene = fg.scene();
    const ambient = new THREE.AmbientLight(0xffffff, 0.8);
    ambient.userData.__argusLight = true;
    scene.add(ambient);
    return () => {
      scene.remove(ambient);
    };
  }, [size.w]);

  // Build a fresh Three.js group for each node — bubble + halo + label.
  // Rebuilt on every render so react-force-graph-3d picks up the new object.
  // 12 nodes × ~3 meshes each = negligible cost.
  const nodeThreeObject = (raw: object) => {
    const node = raw as SectorNode;
    const color = nodeColor(node);
    const r = radiusFor(node.liquidity);
    const colObj = new THREE.Color(color);
    const group = new THREE.Group();

    // Outer halo — additive blend, soft glow
    const halo = new THREE.Mesh(
      new THREE.SphereGeometry(r * 1.4, 32, 24),
      new THREE.MeshBasicMaterial({
        color: colObj,
        transparent: true,
        opacity: isAlerting(node) ? 0.42 : 0.16,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    group.add(halo);

    // Main bubble — solid colored sphere, smooth (48 segments)
    const body = new THREE.Mesh(
      new THREE.SphereGeometry(r, 48, 32),
      new THREE.MeshBasicMaterial({
        color: colObj,
        transparent: true,
        opacity: 0.92,
      }),
    );
    group.add(body);

    // Label sprite, slate-dark text for light bg readability
    const label = makeLabelSprite(node.label, '#1a2230');
    label.position.set(0, r + 10, 0);
    group.add(label);

    return group;
  };

  // Initial camera framing — we re-fit every couple seconds while the
  // simulation is settling, and via onEngineStop once it's done.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || size.w === 0) return;
    const fits = [800, 1800, 3000].map((delay) =>
      setTimeout(() => fg.zoomToFit(1000, 80), delay),
    );
    return () => fits.forEach(clearTimeout);
  }, [size.w]);

  const handleEngineStop = () => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.zoomToFit(1000, 80);
  };

  return (
    <section className="sector-net" ref={wrapRef}>
      <div className="sector-net__canvas">
        {size.w > 0 && (
          <ForceGraph3D
            ref={fgRef as React.MutableRefObject<ForceGraphMethods | undefined>}
            width={size.w}
            height={size.h}
            graphData={snap}
            backgroundColor="rgba(0,0,0,0)"
            showNavInfo={false}
            // Edges — extremely thin, near-black low opacity for the
            // "hair-thin line" look from the reference image
            linkColor={() => 'rgba(40, 50, 70, 0.18)'}
            linkWidth={0.3}
            linkOpacity={0.6}
            linkDirectionalParticles={0}
            // Nodes
            nodeRelSize={1}
            nodeThreeObject={nodeThreeObject}
            nodeThreeObjectExtend={false}
            // Tune force layout for a more organic spread — push nodes
            // apart so the cluster breathes rather than clumping at center
            d3AlphaDecay={0.02}
            d3VelocityDecay={0.4}
            cooldownTicks={150}
            warmupTicks={80}
            onEngineStop={handleEngineStop}
            nodeLabel={(raw: object) => {
              const n = raw as SectorNode;
              const flowSign = n.flow > 0.1 ? '▲' : n.flow < -0.1 ? '▼' : '─';
              const flowClr = n.flow > 0.1 ? '#2c7a3a' : n.flow < -0.1 ? '#a83a3a' : '#5a6a7a';
              return `
                <div class="sector-net__tooltip">
                  <div class="sector-net__tooltip-head" style="color: ${nodeColor(n)}">
                    ${n.label}
                  </div>
                  <div class="sector-net__tooltip-row">
                    LIQ <strong>${Math.round(n.liquidity)}</strong>
                    <span style="color: ${flowClr}">${flowSign} ${(n.flow * 100).toFixed(1)}%</span>
                  </div>
                  ${n.themeTag ? `<div class="sector-net__tooltip-tag">${n.themeTag}</div>` : ''}
                </div>
              `;
            }}
          />
        )}
      </div>
    </section>
  );
};
