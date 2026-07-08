"use client";
// WS6: the plain, printable alternative to the 3D SubmissionTower. Maps each
// eCTD module tile (M1–M5) to the specific Health Canada requirement it
// satisfies and lists its outstanding required items — the "regulatory
// seriousness" view the PM/CDMO personas asked for. Pure presentation over the
// same ModuleTower roll-up the 3D view consumes, plus (when available) the
// gate's per-module missing list.
import type { ModuleTower } from "@/lib/types";

// The Canada eCTD module → requirement it satisfies for an ANDS. Mirrors the
// section_tree module titles/guidance (single source is the backend tree; this
// is the short label a filer reads at a glance).
const MODULE_REQ: Record<string, string> = {
  "1": "Administrative & regional (Canada) — cover letter, forms, bilingual Product Monograph, REP identifiers",
  "2": "CTD Summaries — the QOS-CE and clinical/quality overviews",
  "3": "Quality (CMC) — drug substance & product manufacturing, controls, stability",
  "4": "Nonclinical study reports — not required for a generic ANDS",
  "5": "Clinical study reports — the comparative bioequivalence report(s) vs the Canadian Reference Product",
};

type Missing = { key?: string; title: string; module: string };

const STATE_LABEL: Record<string, string> = {
  pass: "Complete", partial: "In progress", todo: "Not started", na: "N/A",
  conditional: "Change-dependent",
};

export function TowerChecklist({ tower, missing = [], status }: {
  tower: ModuleTower[];
  missing?: Missing[];
  status?: "READY" | "BLOCKED";
}) {
  return (
    <div className="tower-checklist card glass" style={{ padding: "12px 14px" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "baseline", gap: 8, marginBottom: 8 }}>
        <b style={{ fontSize: 13 }}>Module → Health Canada requirement</b>
        {status && (
          <span className={`chip ${status === "READY" ? "ready" : "blocked"}`}
            style={{ fontSize: 11 }}>{status}</span>
        )}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ textAlign: "left" }}>
            <th style={{ padding: "4px 6px" }}>Module</th>
            <th style={{ padding: "4px 6px" }}>Requirement satisfied</th>
            <th style={{ padding: "4px 6px" }}>Status</th>
            <th style={{ padding: "4px 6px" }}>Outstanding</th>
          </tr>
        </thead>
        <tbody>
          {tower.map((m) => {
            const outstanding = missing.filter((x) => String(x.module) === String(m.module));
            const remain = m.state === "na"
              ? 0
              : Math.max(0, (m.required_total || 0) - (m.required_filled || 0));
            return (
              <tr key={m.module} style={{ borderTop: "1px solid var(--hair, #0002)" }}>
                <td style={{ padding: "5px 6px", whiteSpace: "nowrap" }}>
                  <b>M{m.module}</b>
                </td>
                <td style={{ padding: "5px 6px" }}>
                  {MODULE_REQ[String(m.module)] || `Module ${m.module}`}
                </td>
                <td style={{ padding: "5px 6px", whiteSpace: "nowrap" }}>
                  {STATE_LABEL[m.state] || m.state}
                  {m.state !== "na" && m.required_total
                    ? ` (${m.required_filled}/${m.required_total})` : ""}
                </td>
                <td style={{ padding: "5px 6px" }}>
                  {m.state === "na"
                    ? <span className="mut">—</span>
                    : outstanding.length
                      ? <ul style={{ margin: 0, paddingLeft: 16 }}>
                          {outstanding.map((x, i) => (
                            <li key={x.key || i}>{x.title}</li>
                          ))}
                        </ul>
                      : remain > 0
                        ? `${remain} required item(s) still needed`
                        : <span className="chip ready" style={{ fontSize: 11 }}>Done</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mut" style={{ fontSize: 11, marginTop: 8 }}>
        Printable summary of the eCTD module fill and the Health Canada
        requirement each module satisfies. Switch back to the 3D view any time.
      </p>
    </div>
  );
}
