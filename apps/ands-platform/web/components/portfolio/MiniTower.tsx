"use client";
// Compact Module 1–5 roll-up for a portfolio row — five tiny progress bars
// (same .progress pattern as the readiness card), one per eCTD module.
import type { ModuleTower } from "@/lib/types";

export function MiniTower({ tower }: { tower: ModuleTower[] }) {
  return (
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
  );
}
