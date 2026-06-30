"use client";
import { Canvas, useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Group } from "three";
import type { Tile } from "@/lib/types";

const COLOR: Record<string, string> = {
  pass: "#37d39b",
  current: "#5b8cff",
  todo: "#33415e",
};

function Slab({
  y,
  state,
  ready,
}: {
  y: number;
  state: string;
  ready: boolean;
}) {
  const color = COLOR[state] ?? COLOR.todo;
  const emissive =
    state === "current" ? 0.9 : state === "pass" ? (ready ? 0.6 : 0.32) : 0.06;
  return (
    <mesh position={[0, y, 0]} castShadow receiveShadow>
      <boxGeometry args={[2.3, 0.34, 2.3]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={emissive}
        metalness={0.35}
        roughness={0.35}
      />
    </mesh>
  );
}

function Stack({ tiles, ready }: { tiles: Tile[]; ready: boolean }) {
  const g = useRef<Group>(null);
  useFrame((_, dt) => {
    if (g.current) g.current.rotation.y += dt * 0.28;
  });
  const n = tiles.length;
  return (
    <group ref={g}>
      {tiles.map((t, i) => (
        <Slab key={t.key} y={i * 0.46 - (n - 1) * 0.23} state={t.state} ready={ready} />
      ))}
    </group>
  );
}

export default function TowerScene({
  tiles,
  ready,
}: {
  tiles: Tile[];
  ready: boolean;
}) {
  return (
    <Canvas camera={{ position: [3.6, 2.4, 3.6], fov: 42 }} dpr={[1, 2]}>
      <ambientLight intensity={0.7} />
      <pointLight position={[6, 9, 6]} intensity={160} />
      <pointLight position={[-6, -2, -6]} intensity={60} color="#9b6bff" />
      <Stack tiles={tiles} ready={ready} />
    </Canvas>
  );
}
