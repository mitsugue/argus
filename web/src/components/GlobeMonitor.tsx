import React, { useEffect, useMemo, useRef, useState } from 'react';
import Globe, { type GlobeMethods } from 'react-globe.gl';
import * as THREE from 'three';
import type { GlobePillar } from '../types';
import { INITIAL_PILLARS, mutatePillars } from '../mock/data';
import './GlobeMonitor.css';

const PILLAR_COLORS: Record<GlobePillar['color'], string> = {
  cyan: '#00f3ff',
  amber: '#ffb700',
  danger: '#ff3d57',
};

export const GlobeMonitor: React.FC = () => {
  const [pillars, setPillars] = useState<GlobePillar[]>(INITIAL_PILLARS);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [selected, setSelected] = useState<GlobePillar | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const globeRef = useRef<GlobeMethods | undefined>(undefined);

  // Track container size
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

  // Mutate pillar intensities to simulate live updates
  useEffect(() => {
    const t = setInterval(() => setPillars((prev) => mutatePillars(prev)), 1800);
    return () => clearInterval(t);
  }, []);

  // Auto-rotate
  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    const controls = g.controls() as unknown as {
      autoRotate: boolean;
      autoRotateSpeed: number;
      enableZoom: boolean;
      enablePan: boolean;
    };
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.35;
    controls.enableZoom = false;
    controls.enablePan = false;
    g.pointOfView({ lat: 20, lng: 100, altitude: 2.4 }, 0);
  }, [size.w, size.h]);

  // HUD-styled globe material
  const globeMaterial = useMemo(() => {
    const m = new THREE.MeshPhongMaterial({
      color: new THREE.Color('#001a1f'),
      emissive: new THREE.Color('#001218'),
      shininess: 4,
      transparent: true,
      opacity: 0.72,
      wireframe: false,
    });
    return m;
  }, []);

  // Wireframe overlay sphere
  const customLayer = useMemo(() => {
    const geo = new THREE.SphereGeometry(100.4, 64, 32);
    const mat = new THREE.MeshBasicMaterial({
      color: new THREE.Color('#00f3ff'),
      wireframe: true,
      transparent: true,
      opacity: 0.08,
    });
    return new THREE.Mesh(geo, mat);
  }, []);

  // Inject wireframe overlay once globe scene is ready
  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    const scene = g.scene();
    scene.add(customLayer);
    return () => {
      scene.remove(customLayer);
    };
  }, [customLayer, size.w]);

  const focus = (p: GlobePillar) => {
    setSelected(p);
    const g = globeRef.current;
    if (g) g.pointOfView({ lat: p.lat, lng: p.lng, altitude: 1.6 }, 1100);
  };

  return (
    <section className="globe-monitor hud-corner" ref={wrapRef}>
      <div className="globe-monitor__title">
        <span className="hud-panel__title">GEO INTEL // EARTH MON</span>
        <span className="globe-monitor__count">SIGNALS · {pillars.length}</span>
      </div>

      <div className="globe-monitor__canvas">
        {size.w > 0 && (
          <Globe
            ref={globeRef as React.MutableRefObject<GlobeMethods | undefined>}
            width={size.w}
            height={size.h - 40}
            backgroundColor="rgba(0,0,0,0)"
            showAtmosphere
            atmosphereColor="#00f3ff"
            atmosphereAltitude={0.18}
            globeMaterial={globeMaterial}
            showGraticules
            pointsData={pillars}
            pointLat={(d: object) => (d as GlobePillar).lat}
            pointLng={(d: object) => (d as GlobePillar).lng}
            pointColor={(d: object) => PILLAR_COLORS[(d as GlobePillar).color]}
            pointAltitude={(d: object) => (d as GlobePillar).intensity * 0.45}
            pointRadius={0.42}
            pointResolution={6}
            pointLabel={(d: object) => {
              const p = d as GlobePillar;
              return `<div style="font-family: 'JetBrains Mono', monospace; font-size: 10px; padding: 4px 8px; border: 1px solid #00f3ff; background: rgba(0,0,0,0.85); color: #d6f5f7; letter-spacing: 1px;">
                <div style="color:#00f3ff">${p.label} · ${p.region.toUpperCase()}</div>
                <div style="color:#ffb700">INT ${(p.intensity * 100).toFixed(0)}%</div>
                <div>${p.detail}</div>
              </div>`;
            }}
            onPointClick={(d: object) => focus(d as GlobePillar)}
            ringsData={pillars.filter((p) => p.intensity > 0.7)}
            ringLat={(d: object) => (d as GlobePillar).lat}
            ringLng={(d: object) => (d as GlobePillar).lng}
            ringColor={(d: object) => () => PILLAR_COLORS[(d as GlobePillar).color] + 'cc'}
            ringMaxRadius={5}
            ringPropagationSpeed={2}
            ringRepeatPeriod={1400}
          />
        )}
      </div>

      <div className="globe-monitor__readout">
        {selected ? (
          <>
            <div className="globe-monitor__row">
              <span className="hud-label">TARGET</span>
              <span className="hud-value">{selected.label}</span>
            </div>
            <div className="globe-monitor__row">
              <span className="hud-label">REGION</span>
              <span style={{ color: 'var(--hud-amber)', fontSize: 11 }}>{selected.region.toUpperCase()}</span>
            </div>
            <div className="globe-monitor__row">
              <span className="hud-label">INT</span>
              <span style={{ color: PILLAR_COLORS[selected.color], fontSize: 12 }}>
                {(selected.intensity * 100).toFixed(0)}%
              </span>
            </div>
            <div className="globe-monitor__detail">{selected.detail}</div>
          </>
        ) : (
          <div className="globe-monitor__hint">タップ / クリックでスポット選択 · ドラッグで回転</div>
        )}
      </div>
    </section>
  );
};
