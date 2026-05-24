import React, { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph3D, { type ForceGraphMethods } from 'react-force-graph-3d';
import * as THREE from 'three';
import type { NetworkSnapshot, SectorNode } from '../types/sector';
import { breatheNetwork, seedNetwork } from '../mock/sectors';
import './SectorNetwork.css';

// Blue-gray palette — base for the cell-membrane look. Red only for alerts.
const COLOR = {
  base: new THREE.Color('#4a5e7a'),
  baseGlow: new THREE.Color('#6a86a8'),
  warm: new THREE.Color('#a87e4a'),
  alert: new THREE.Color('#ff3d4f'),
  link: 'rgba(150, 180, 210, 0.18)',
};

function colorFor(node: SectorNode): THREE.Color {
  if (node.alert === 'alert') return COLOR.alert;
  if (node.alert === 'warm') return COLOR.warm;
  // Subtle flow tint: positive inflow → brighter blue-gray, outflow → darker
  const tint = COLOR.base.clone();
  if (node.flow > 0) tint.lerp(COLOR.baseGlow, Math.min(1, node.flow));
  return tint;
}

/** Convert liquidity (~100..2000) to a node radius (~3..14). */
function radiusFor(liquidity: number): number {
  return 2.4 + Math.sqrt(liquidity) * 0.28;
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

  // Per-node Three.js mesh: a soft, semi-transparent sphere ("cell").
  // We rebuild meshes on liquidity change so node size animates.
  const nodeThreeObject = useMemo(() => {
    return (raw: object) => {
      const node = raw as SectorNode;
      const r = radiusFor(node.liquidity);
      const color = colorFor(node);
      const group = new THREE.Group();

      // Outer membrane — wireframe-ish soft shell
      const membrane = new THREE.Mesh(
        new THREE.SphereGeometry(r, 24, 16),
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: 0.18,
        }),
      );
      group.add(membrane);

      // Inner core — slightly smaller, more saturated
      const core = new THREE.Mesh(
        new THREE.SphereGeometry(r * 0.62, 20, 12),
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: 0.55,
        }),
      );
      group.add(core);

      // Alert nodes get a thin emissive halo (faked via a slightly larger
      // mesh with additive blending)
      if (node.alert === 'alert') {
        const halo = new THREE.Mesh(
          new THREE.SphereGeometry(r * 1.18, 24, 16),
          new THREE.MeshBasicMaterial({
            color: COLOR.alert,
            transparent: true,
            opacity: 0.12,
            blending: THREE.AdditiveBlending,
          }),
        );
        group.add(halo);
      }

      return group;
    };
  }, []);

  // Cool the camera distance once on first layout
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || size.w === 0) return;
    // Slight delay so the force simulation has placed nodes before zoom
    const t = setTimeout(() => {
      fg.zoomToFit(800, 40);
    }, 300);
    return () => clearTimeout(t);
  }, [size.w]);

  return (
    <section className="sector-net hud-corner" ref={wrapRef}>
      <span className="panel-tab">LIQUIDITY NET · {snap.nodes.length}</span>

      <div className="sector-net__canvas">
        {size.w > 0 && (
          <ForceGraph3D
            ref={fgRef as React.MutableRefObject<ForceGraphMethods | undefined>}
            width={size.w}
            height={size.h}
            graphData={snap}
            backgroundColor="rgba(0,0,0,0)"
            showNavInfo={false}
            // Edges
            linkColor={() => COLOR.link}
            linkWidth={0.4}
            linkOpacity={0.6}
            linkDirectionalParticles={0}
            // Nodes
            nodeRelSize={1}
            nodeThreeObject={nodeThreeObject}
            nodeThreeObjectExtend={false}
            nodeLabel={(raw: object) => {
              const n = raw as SectorNode;
              const flowSign = n.flow > 0.1 ? '▲' : n.flow < -0.1 ? '▼' : '─';
              return `
                <div class="sector-net__tooltip">
                  <div class="sector-net__tooltip-head ${n.alert === 'alert' ? 'is-alert' : ''}">
                    ${n.label}
                  </div>
                  <div class="sector-net__tooltip-row">
                    LIQ <strong>${Math.round(n.liquidity)}</strong> ${flowSign}
                    ${(n.flow * 100).toFixed(1)}%
                  </div>
                  ${n.themeTag ? `<div class="sector-net__tooltip-tag">${n.themeTag}</div>` : ''}
                </div>
              `;
            }}
          />
        )}
      </div>

      <div className="sector-net__legend">
        <span className="sector-net__legend-row">
          <i className="sector-net__sw sector-net__sw--base" />
          BLUE-GRAY · BASE FLOW
        </span>
        <span className="sector-net__legend-row">
          <i className="sector-net__sw sector-net__sw--alert" />
          RED · ANOMALY
        </span>
      </div>
    </section>
  );
};
