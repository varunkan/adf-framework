"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { Tile } from "@/lib/types";

const TowerScene = dynamic(() => import("./TowerScene"), { ssr: false });

function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(
      (window as any).WebGLRenderingContext &&
      (c.getContext("webgl") || c.getContext("experimental-webgl"))
    );
  } catch {
    return false;
  }
}
function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );
}

// Accessible 2D fallback — a CSS-3D isometric stack (no GPU, no animation under
// reduced-motion). Always renders, so the experience never depends on WebGL.
function CssTower({ tiles, ready }: { tiles: Tile[]; ready: boolean }) {
  return (
    <div className="css-tower" data-ready={ready}>
      <div className="stack">
        {tiles.map((t) => (
          <div key={t.key} className={`slab ${t.state}`} title={t.label}>
            {t.label.split(" ")[0]}
          </div>
        ))}
      </div>
    </div>
  );
}

export function SubmissionTower({
  tiles,
  status,
}: {
  tiles: Tile[];
  status: "READY" | "BLOCKED";
}) {
  const [webgl, setWebgl] = useState(false);
  useEffect(() => {
    setWebgl(hasWebGL() && !reducedMotion());
  }, []);
  const ready = status === "READY";
  const passed = tiles.filter((t) => t.state === "pass").length;
  return (
    <div className="tower-host" role="img"
      aria-label={`Submission tower — ${passed} of ${tiles.length} stages complete, ${status}`}>
      {webgl ? (
        <TowerScene tiles={tiles} ready={ready} />
      ) : (
        <CssTower tiles={tiles} ready={ready} />
      )}
      <div className="tower-cap">
        Your submission · <b>Module 1–5</b> — {passed}/{tiles.length} green
        {ready ? " · READY ✦" : ""}
      </div>
    </div>
  );
}
