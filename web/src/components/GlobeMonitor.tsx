import React, { useEffect, useMemo, useRef, useState } from 'react';
import Globe, { type GlobeMethods } from 'react-globe.gl';
import * as THREE from 'three';
import type { GlobePillar, GlobePulse } from '../types';
import { flag } from '../util/flag';
import './GlobeMonitor.css';

const PILLAR_COLORS: Record<GlobePillar['color'], string> = {
  cyan: '#00f3ff',
  amber: '#ffb700',
  danger: '#ff3d57',
};

type CountryFeature = {
  type: 'Feature';
  properties: Record<string, unknown>;
  // GeoJSON Polygon / MultiPolygon — coords nesting varies, kept loose intentionally
  geometry: { type: string; coordinates: number[] };
};

interface Props {
  pillars: GlobePillar[];
  selected: GlobePillar | null;
  onSelect: (id: string | null) => void;
  pulses: GlobePulse[];
}

export const GlobeMonitor: React.FC<Props> = ({ pillars, selected, onSelect, pulses }) => {
  // Quick lookup of which pillars are currently emitting
  const pulsingIds = useMemo(() => {
    const s = new Set<string>();
    for (const p of pulses) s.add(p.pillarId);
    return s;
  }, [pulses]);

  const pulsingColor = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of pulses) m.set(p.pillarId, p.color);
    return m;
  }, [pulses]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [countries, setCountries] = useState<CountryFeature[]>([]);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const hasIntroAnimated = useRef(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${import.meta.env.BASE_URL}countries.geojson`)
      .then((r) => r.json())
      .then((data: { features: CountryFeature[] }) => {
        if (!cancelled) setCountries(data.features ?? []);
      })
      .catch(() => {
        /* globe still works without borders */
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    const controls = g.controls() as unknown as {
      autoRotate: boolean;
      autoRotateSpeed: number;
      enableZoom: boolean;
      enablePan: boolean;
      enableRotate: boolean;
    };
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.32;
    controls.enableZoom = false;
    controls.enablePan = false;
    // enableRotate must be true for autoRotate to run AND so finger drag
    // can spin the globe. Page-level horizontal scroll is already locked
    // via touch-action: pan-y on body, so we can let the canvas grab
    // pointer drags freely.
    controls.enableRotate = true;
    if (!hasIntroAnimated.current) {
      // Start far, zoom in. The wireframe sphere lives in the same scene
      // so it grows together with the textured globe.
      g.pointOfView({ lat: 20, lng: 100, altitude: 4.5 }, 0);
      requestAnimationFrame(() => {
        g.pointOfView({ lat: 20, lng: 100, altitude: 2.3 }, 1600);
      });
      hasIntroAnimated.current = true;
    } else {
      g.pointOfView({ lat: 20, lng: 100, altitude: 2.3 }, 0);
    }
  }, [size.w, size.h]);

  // Camera follows selected pillar
  useEffect(() => {
    const g = globeRef.current;
    if (!g || !selected) return;
    g.pointOfView({ lat: selected.lat, lng: selected.lng, altitude: 1.7 }, 1100);
  }, [selected?.id]);

  const globeMaterial = useMemo(
    () =>
      new THREE.MeshPhongMaterial({
        color: new THREE.Color('#001a1f'),
        emissive: new THREE.Color('#001218'),
        shininess: 4,
        transparent: true,
        opacity: 0.72,
      }),
    []
  );

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

  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    const scene = g.scene();
    scene.add(customLayer);
    return () => {
      scene.remove(customLayer);
    };
  }, [customLayer, size.w]);

  return (
    <section className="globe-monitor hud-corner" ref={wrapRef}>
      <span className="panel-tab">
        GEO INTEL · {pillars.length} SIGNALS
      </span>

      <div className="globe-monitor__canvas">
        {size.w > 0 && (
          <Globe
            ref={globeRef as React.MutableRefObject<GlobeMethods | undefined>}
            width={size.w}
            height={size.h}
            backgroundColor="rgba(0,0,0,0)"
            showAtmosphere
            atmosphereColor="#00f3ff"
            atmosphereAltitude={0.18}
            globeMaterial={globeMaterial}
            showGraticules
            pointsData={pillars}
            pointLat={(d: object) => (d as GlobePillar).lat}
            pointLng={(d: object) => (d as GlobePillar).lng}
            pointColor={(d: object) => {
              const p = d as GlobePillar;
              const pulseColor = pulsingColor.get(p.id);
              return pulseColor ?? PILLAR_COLORS[p.color];
            }}
            pointAltitude={(d: object) => {
              const p = d as GlobePillar;
              const base = p.intensity * 0.45;
              return pulsingIds.has(p.id) ? base + 0.25 : base;
            }}
            pointRadius={(d: object) => {
              const p = d as GlobePillar;
              if (pulsingIds.has(p.id)) return 0.72;
              return p.id === selected?.id ? 0.6 : 0.42;
            }}
            pointResolution={6}
            pointLabel={(d: object) => {
              const p = d as GlobePillar;
              return `<div style="font-family: 'JetBrains Mono', monospace; font-size: 10px; padding: 5px 9px; border: 1px solid ${PILLAR_COLORS[p.color]}; background: rgba(0,0,0,0.88); color: #d6f5f7; letter-spacing: 1px; min-width: 180px;">
                <div style="color:${PILLAR_COLORS[p.color]}; font-size: 11px;">${flag(p.countryCode)} ${p.country} · ${p.label}</div>
                <div style="color:#ffb700; margin: 2px 0;">SRC · ${p.source} &nbsp;|&nbsp; INT ${(p.intensity * 100).toFixed(0)}%</div>
                <div style="color:#d6f5f7; max-width: 240px; line-height: 1.5;">${p.headline}</div>
              </div>`;
            }}
            onPointClick={(d: object) => onSelect((d as GlobePillar).id)}
            ringsData={pulses}
            ringLat={(d: object) => (d as GlobePulse).lat}
            ringLng={(d: object) => (d as GlobePulse).lng}
            ringColor={(d: object) => () => (d as GlobePulse).color}
            ringMaxRadius={7}
            ringPropagationSpeed={5}
            ringRepeatPeriod={420}
            polygonsData={countries}
            polygonGeoJsonGeometry={(d: object) => (d as CountryFeature).geometry}
            polygonAltitude={0.006}
            polygonCapColor={(d: object) => {
              const f = d as CountryFeature;
              const sel = selected?.country;
              const name = (f.properties as { ADMIN?: string; NAME?: string }).ADMIN ?? (f.properties as { NAME?: string }).NAME;
              return sel && name === sel ? 'rgba(0, 243, 255, 0.22)' : 'rgba(0, 243, 255, 0.05)';
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

      {selected && (
        <div className="globe-monitor__readout">
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
        </div>
      )}
    </section>
  );
};
