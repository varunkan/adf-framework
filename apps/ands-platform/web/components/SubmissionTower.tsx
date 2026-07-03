"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { ModuleTower, Tile } from "@/lib/types";
import { useTowerView } from "@/lib/useTowerView";
import { TowerChecklist } from "./TowerChecklist";

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
  missing = [],
}: {
  tiles: Tile[];
  status: "READY" | "BLOCKED";
  modules?: ModuleTower[];
  // WS6: the gate's per-module missing list, shown as outstanding items in the
  // plain checklist view (optional — the tower renders without it).
  missing?: { key?: string; title: string; module: string }[];
}) {
  const [webgl, setWebgl] = useState(false);
  const [view, setView] = useTowerView();
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

  // WS6: the checklist wants the FULL M1–M5 roll-up (including 'na' modules,
  // which it labels "not required"), not the na-filtered tile list the 3D
  // view stacks. Prefer the real modules roll-up; synthesize one from the
  // stage tiles when the caller has no per-module data.
  const checklistRows: ModuleTower[] = modules
    ? modules
    : display.map((t, i) => ({
        module: String(i + 1),
        state: t.state === "pass" ? "pass" : t.state === "current" ? "partial" : "todo",
        required_total: 0,
        required_filled: 0,
      }));

  const Toggle = (
    <div role="group" aria-label="Tower view" style={{ display: "inline-flex",
      gap: 4, marginBottom: 8 }}>
      <button type="button" className={`chip ${view === "tower" ? "ready" : ""}`}
        aria-pressed={view === "tower"} onClick={() => setView("tower")}
        style={{ fontSize: 11 }} title="3D submission tower">3D view</button>
      <button type="button" className={`chip ${view === "checklist" ? "ready" : ""}`}
        aria-pressed={view === "checklist"} onClick={() => setView("checklist")}
        style={{ fontSize: 11 }} title="Plain, printable module → requirement checklist">
        Checklist
      </button>
    </div>
  );

  if (view === "checklist") {
    return (
      <div className="tower-host">
        {Toggle}
        <TowerChecklist tower={checklistRows} missing={missing} status={status} />
      </div>
    );
  }

  return (
    <div className="tower-host" role="img"
      aria-label={`Submission tower — ${passed} of ${display.length} ${modules ? "modules placed" : "stages complete"}, ${status}`}>
      {Toggle}
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
