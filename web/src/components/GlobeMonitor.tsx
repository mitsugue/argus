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

// ISO alpha-2 → regional indicator emoji (flag)
const flag = (code: string) =>
  code
    .toUpperCase()
    .split('')
    .map((c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65))
    .join('');

type CountryFeature = {
  type: 'Feature';
  properties: Record<string, unknown>;
  // GeoJSON Polygon / MultiPolygon — coords nesting varies, kept loose intentionally
  geometry: { type: string; coordinates: number[] };
};

export const GlobeMonitor: React.FC = () => {
  const [pillars, setPillars] = useState<GlobePillar[]>(INITIAL_PILLARS);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [selected, setSelected] = useState<GlobePillar | null>(null);
  const [countries, setCountries] = useState<CountryFeature[]>([]);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const globeRef = useRef<GlobeMethods | undefined>(undefined);

  // Load country borders once
  useEffect(() => {
    let cancelled = false;
    fetch('/countries.geojson')
      .then((r) => r.json())
      .then((data: { features: CountryFeature[] }) => {
        if (!cancelled) setCountries(data.features ?? []);
      })
      .catch(() => {
        /* ignore — globe still works without borders */
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
              return `<div style="font-family: 'JetBrains Mono', monospace; font-size: 10px; padding: 5px 9px; border: 1px solid ${PILLAR_COLORS[p.color]}; background: rgba(0,0,0,0.88); color: #d6f5f7; letter-spacing: 1px; min-width: 180px;">
                <div style="color:${PILLAR_COLORS[p.color]}; font-size: 11px;">${flag(p.countryCode)} ${p.country} · ${p.label}</div>
                <div style="color:#ffb700; margin: 2px 0;">SRC · ${p.source} &nbsp;|&nbsp; INT ${(p.intensity * 100).toFixed(0)}%</div>
                <div style="color:#d6f5f7; max-width: 240px; line-height: 1.5;">${p.headline}</div>
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
            polygonsData={countries}
            polygonGeoJsonGeometry={(d: object) => (d as CountryFeature).geometry}
            polygonAltitude={0.006}
            polygonCapColor={(d: object) => {
              const f = d as CountryFeature;
              const sel = selected?.country;
              const name = (f.properties as { ADMIN?: string; NAME?: string }).ADMIN ?? (f.properties as { NAME?: string }).NAME;
              return sel && name === sel ? 'rgba(0, 243, 255, 0.18)' : 'rgba(0, 243, 255, 0.05)';
            }}
            polygonSideColor={() => 'rgba(0, 243, 255, 0.04)'}
            polygonStrokeColor={() => 'rgba(0, 243, 255, 0.55)'}
            polygonLabel={(d: object) => {
              const props = (d as CountryFeature).properties as { ADMIN?: string; ISO_A2?: string };
              const name = props.ADMIN ?? '—';
              const code = props.ISO_A2 ?? '';
              return `<div style="font-family: 'JetBrains Mono', monospace; font-size: 10px; padding: 3px 7px; border: 1px solid rgba(0,243,255,0.6); background: rgba(0,0,0,0.85); color: #00f3ff; letter-spacing: 1px;">
                ${code && code !== '-99' ? flag(code) + ' ' : ''}${name}
              </div>`;
            }}
          />
        )}
      </div>

      <div className="globe-monitor__readout">
        {selected ? (
          <>
            <div className="globe-monitor__row">
              <span className="hud-label">SRC</span>
              <span className="hud-value" style={{ fontSize: 12 }}>
                <span style={{ marginRight: 6 }}>{flag(selected.countryCode)}</span>
                {selected.country}
              </span>
            </div>
            <div className="globe-monitor__row">
              <span className="hud-label">OUTLET</span>
              <span style={{ color: 'var(--hud-amber)', fontSize: 11 }}>{selected.source}</span>
            </div>
            <div className="globe-monitor__row">
              <span className="hud-label">{selected.label} · INT</span>
              <span style={{ color: PILLAR_COLORS[selected.color], fontSize: 12 }}>
                {(selected.intensity * 100).toFixed(0)}%
              </span>
            </div>
            <div className="globe-monitor__detail">{selected.headline}</div>
          </>
        ) : (
          <div className="globe-monitor__hint">タップ / クリックでスポット選択 · ドラッグで回転</div>
        )}
      </div>
    </section>
  );
};
