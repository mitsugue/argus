import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Environment, MeshTransmissionMaterial, Html } from '@react-three/drei';
import { hierarchy, pack, type HierarchyCircularNode } from 'd3-hierarchy';
import * as THREE from 'three';
import type { AssetNode, AssetTree } from '../types/asset';
import { breatheAssets, seedAssets } from '../mock/assets';
import './SectorBubbles.css';

// ─────────────────────────────────────────────────────────────────────────
// Layout — d3-hierarchy.pack on the asset tree, producing a flat array of
// circles with { x, y, r, depth, data }. We use a unit square then scale
// at render time to fit the canvas.
// ─────────────────────────────────────────────────────────────────────────

type PackNode = HierarchyCircularNode<AssetNode | AssetTree>;

const PACK_SIZE = 100;

function computePack(tree: AssetTree): PackNode[] {
  const root = hierarchy<AssetNode | AssetTree>(tree)
    .sum((d) => ('children' in d && d.children && d.children.length ? 0 : d.value))
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));

  const layout = pack<AssetNode | AssetTree>()
    .size([PACK_SIZE, PACK_SIZE])
    .padding(1.2);

  const out: PackNode[] = [];
  layout(root).each((node) => {
    if (node.depth === 0) return; // skip the synthetic root
    out.push(node);
  });
  return out;
}

// ─────────────────────────────────────────────────────────────────────────
// Single bubble — glass material, tweens between target radius/position
// so the cluster breathes smoothly when the snapshot changes.
// ─────────────────────────────────────────────────────────────────────────

interface BubbleProps {
  target: { x: number; y: number; r: number };
  label: string;
  depth: number;
  alert?: boolean;
  showLabel: boolean;
}

const Bubble: React.FC<BubbleProps> = ({ target, label, depth, alert, showLabel }) => {
  const meshRef = useRef<THREE.Mesh>(null);
  // Local interpolation state
  const current = useRef({ x: target.x, y: target.y, r: target.r });

  useFrame((_, delta) => {
    const mesh = meshRef.current;
    if (!mesh) return;
    // Critically-damped easing toward the target each frame
    const k = Math.min(1, delta * 4);
    current.current.x += (target.x - current.current.x) * k;
    current.current.y += (target.y - current.current.y) * k;
    current.current.r += (target.r - current.current.r) * k;
    mesh.position.set(current.current.x, -current.current.y, depth * 0.4);
    mesh.scale.setScalar(current.current.r);
  });

  // Inner bubbles are more transparent / smaller refraction so the parent
  // glass can be seen "containing" them
  const isChild = depth >= 2;

  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[1, 48, 48]} />
      <MeshTransmissionMaterial
        thickness={isChild ? 0.6 : 1.4}
        roughness={0.08}
        transmission={1}
        ior={1.32}
        chromaticAberration={0.04}
        backside={false}
        anisotropy={0.18}
        distortion={0.1}
        distortionScale={0.4}
        temporalDistortion={0.08}
        attenuationDistance={isChild ? 6 : 12}
        attenuationColor={alert ? '#ff7a7a' : '#bcdcef'}
        color={alert ? '#ffb0b0' : '#cfe6f4'}
      />
      {showLabel && (
        <Html
          center
          distanceFactor={32}
          zIndexRange={[10, 0]}
          style={{ pointerEvents: 'none' }}
        >
          <div className={`asset-label asset-label--d${depth}${alert ? ' is-alert' : ''}`}>
            {label}
          </div>
        </Html>
      )}
    </mesh>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// Scene — pack layout, lighting, environment.
// ─────────────────────────────────────────────────────────────────────────

interface SceneProps {
  tree: AssetTree;
}

const Scene: React.FC<SceneProps> = ({ tree }) => {
  const packed = useMemo(() => computePack(tree), [tree]);

  return (
    <>
      {/* Soft sky-like light + a faint key. Environment supplies the
          reflections that give the glass its lifelike quality. */}
      <ambientLight intensity={0.6} />
      <directionalLight position={[10, 14, 8]} intensity={0.65} color="#ffffff" />
      <directionalLight position={[-8, -4, -6]} intensity={0.3} color="#aac8e0" />

      {/* "studio" preset gives clean spec highlights without HDR download */}
      <Environment preset="city" />

      <group position={[-PACK_SIZE / 2, PACK_SIZE / 2, 0]}>
        {packed.map((node) => {
          const data = node.data as AssetNode;
          const showLabel = node.r > 5;
          return (
            <Bubble
              key={data.id}
              target={{ x: node.x, y: node.y, r: node.r }}
              label={data.label}
              depth={node.depth}
              alert={!!data.alert}
              showLabel={showLabel}
            />
          );
        })}
      </group>
    </>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// Top-level component — drives the breath loop and frames the Canvas.
// ─────────────────────────────────────────────────────────────────────────

export const SectorBubbles: React.FC = () => {
  const [tree, setTree] = useState<AssetTree>(() => seedAssets());

  useEffect(() => {
    const t = setInterval(() => {
      setTree((prev) => breatheAssets(prev));
    }, 1600);
    return () => clearInterval(t);
  }, []);

  return (
    <section className="sector-bubbles">
      <Canvas
        camera={{ position: [0, 0, 120], fov: 40, near: 0.1, far: 1000 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true }}
      >
        <Scene tree={tree} />
      </Canvas>
    </section>
  );
};
