"use client";
// Compact Module 1–5 roll-up for a portfolio row — five tiny progress bars
// (same .progress pattern as the readiness card), one per eCTD module.
// WS6: a per-row toggle swaps the bars for the plain module→requirement
// checklist (the "gimmick" personas' preferred serious view); the choice is
// the same persisted preference the 3D SubmissionTower uses.
import type { ModuleTower } from "@/lib/types";
import { useTowerView } from "@/lib/useTowerView";
import { TowerChecklist } from "@/components/TowerChecklist";

// Round-9 (operations MAJOR, n=2; labelling_specialist): Module 1 labelling
// completeness (PM + labels) with a missing-French flag, derived from the
// dossier's real section state — never fabricated when content isn't loaded.
export type M1Labelling = {
  total: number;    // labelling documents (1.3.x) applicable on this dossier
  filled: number;   // of those, complete
  frMissing: string[]; // bilingual labelling sections whose FR version is absent
};

function LabellingChip({ lab }: { lab?: M1Labelling }) {
  if (!lab || !lab.total) return null;
  const bad = lab.frMissing.length > 0 || lab.filled < lab.total;
  return (
    <span className={`chip ${bad ? "blocked" : "ready"}`}
      style={{ fontSize: 10, padding: "0 6px" }}
      title={
        `Module 1 labelling (1.3.x — product monograph, labels/mock-ups): ` +
        `${lab.filled} of ${lab.total} complete.` +
        (lab.frMissing.length
          ? ` French version missing on: ${lab.frMissing.join(", ")} — the ` +
            `EN/FR product monograph pair is required at 1.3.1.`
          : " French versions present where required.")
      }>
      M1 labelling {lab.filled}/{lab.total}
      {lab.frMissing.length ? " · ⚠ FR missing" : ""}
    </span>
  );
}

export function MiniTower({ tower, missing = [], labelling }: {
  tower: ModuleTower[];
  missing?: { key?: string; title: string; module: string }[];
  labelling?: M1Labelling;
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
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 6,
          marginBottom: 4 }}>
          <LabellingChip lab={labelling} />
          {toggle}
        </div>
        <TowerChecklist tower={tower} missing={missing} />
      </div>
    );
  }
  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column",
      gap: 4, alignItems: "flex-end" }}>
      <span style={{ display: "inline-flex", gap: 6 }}>
        <LabellingChip lab={labelling} />
        {toggle}
      </span>
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
