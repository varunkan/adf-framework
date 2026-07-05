"use client";
// Compact Module 1–5 roll-up for a portfolio row — five tiny progress bars
// (same .progress pattern as the readiness card), one per eCTD module.
// WS6: a per-row toggle swaps the bars for the plain module→requirement
// checklist (the "gimmick" personas' preferred serious view); the choice is
// the same persisted preference the 3D SubmissionTower uses.
import type { ModuleTower } from "@/lib/types";
import { useTowerView } from "@/lib/useTowerView";
import { TowerChecklist } from "@/components/TowerChecklist";

export function MiniTower({ tower, missing = [] }: {
  tower: ModuleTower[];
  missing?: { key?: string; title: string; module: string }[];
}) {
  const [view, setView] = useTowerView();
  const toggle = (
    <button type="button" className="chip" style={{ fontSize: 10, padding: "0 6px" }}
      aria-pressed={view === "checklist"}
      title={view === "checklist" ? "Show the module bars" : "Show the module → requirement checklist"}
      onClick={() => setView(view === "checklist" ? "tower" : "checklist")}>
      {view === "checklist" ? "Bars" : "Checklist"}
    </button>
  );
  if (view === "checklist") {
    return (
      <div style={{ width: "100%", minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 4 }}>
          {toggle}
        </div>
        <TowerChecklist tower={tower} missing={missing} />
      </div>
    );
  }
  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column",
      gap: 4, alignItems: "flex-end" }}>
      {toggle}
      <div
        style={{ display: "flex", gap: 8, alignItems: "flex-end" }}
        aria-label="Module completion, Modules 1 to 5"
      >
      {tower.map((t) => {
        const pct =
          t.state === "na" || !t.required_total
            ? 0
            : Math.round((t.required_filled / t.required_total) * 100);
        const label =
          t.state === "na"
            ? `Module ${t.module}: not applicable`
            : `Module ${t.module}: ${t.required_filled} of ${t.required_total} required documents`;
        return (
          <div key={t.module} style={{ textAlign: "center" }} title={label}>
            <div
              className="progress"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pct}
              aria-label={label}
              style={{ width: 34, margin: 0, opacity: t.state === "na" ? 0.35 : 1 }}
            >
              <i style={{ width: `${pct}%` }} />
            </div>
            <span className="mut" style={{ fontSize: 10 }}>M{t.module}</span>
          </div>
        );
      })}
      </div>
    </div>
  );
}
