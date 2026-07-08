"use client";
// Compact Module 1–5 roll-up for a portfolio row — five tiny progress bars
// (same .progress pattern as the readiness card), one per eCTD module.
//
// Visual-QA fix (2026-07-07): a portfolio row is a fixed-height, scan-at-a-
// glance roll-up. An earlier change wired the shared `useTowerView` toggle in
// here, and because that preference DEFAULTS to "checklist", every row rendered
// a full ~1,600px module→requirement TABLE inside this ~230px cell — blowing
// each row to 1625px tall and pushing the grid off-screen. The eCTD-substance
// checklist already lives (correctly, full-width) on the builder's
// SubmissionTower; the portfolio glance stays the compact bars, always.
import type { ModuleTower } from "@/lib/types";

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
  // `missing` is accepted for API compatibility with the builder tower but the
  // compact portfolio glance does not render the per-requirement list.
  missing?: { key?: string; title: string; module: string }[];
  labelling?: M1Labelling;
}) {
  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column",
      gap: 4, alignItems: "flex-end" }}>
      <span style={{ display: "inline-flex", gap: 6 }}>
        <LabellingChip lab={labelling} />
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
