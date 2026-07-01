"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { ModuleTower, Tile } from "@/lib/types";

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

const MODULE_STATE: Record<string, Tile["state"]> = {
  pass: "pass",
  partial: "current",
  todo: "todo",
};

export function SubmissionTower({
  tiles,
  status,
  modules,
}: {
  tiles: Tile[];
  status: "READY" | "BLOCKED";
  modules?: ModuleTower[];
}) {
  const [webgl, setWebgl] = useState(false);
  useEffect(() => {
    setWebgl(hasWebGL() && !reducedMotion());
  }, []);
  const ready = status === "READY";

  // In the content step the tower shows the literal eCTD Module fill; elsewhere
  // it shows overall journey progress. Modules that don't apply to a generic
  // ANDS (e.g. Module 4 nonclinical) are 'na' and are excluded entirely — they
  // are never outstanding work, so the tower is completable.
  const display: Tile[] = modules
    ? modules
        .filter((m) => m.state !== "na")
        .map((m) => ({
          key: `m${m.module}`,
          label: `Module ${m.module}`,
          state: MODULE_STATE[m.state] ?? "todo",
          reg: "",
        }))
    : tiles;
  const passed = display.filter((t) => t.state === "pass").length;

  return (
    <div className="tower-host" role="img"
      aria-label={`Submission tower — ${passed} of ${display.length} ${modules ? "modules placed" : "stages complete"}, ${status}`}>
      {webgl ? (
        <TowerScene tiles={display} ready={ready} />
      ) : (
        <CssTower tiles={display} ready={ready} />
      )}
      <div className="tower-cap">
        {modules ? (
          <>Placing into <b>Module 1–5</b> — {passed}/{display.length} complete</>
        ) : (
          <>Your submission · <b>Module 1–5</b> — {passed}/{display.length} green{ready ? " · READY ✦" : ""}</>
        )}
      </div>
    </div>
  );
}
