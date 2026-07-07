"use client";
// Round-9 catalog minor — "No cost/timeline anchor for a filing" (n=2;
// startup_founder). A rough, SOURCED cost + timeline anchor on the catalog so
// a founder can see where they stand up front.
//
// HONEST: every dollar figure below is the SAME verbatim Fees-Order figure the
// in-app fee engine uses (services/dossier fees engine, mirrored from the mesh
// fees service) — nothing is invented here. Fees are CPI-indexed each April 1;
// the label names the fiscal year and tells the reader to verify the current
// Fees Order before budgeting. Timelines repeat the product's existing,
// vetted claims (Company ID ~2 weeks; screening ~45 days; ANDS science review
// ~180 days) as TYPICAL service standards, not guarantees.
import { useState } from "react";
import { ChevronDown, ChevronRight, Landmark } from "lucide-react";

// Verbatim from the dossier-service fee engine (Schedule 1 "Comparative
// studies" grouping — an ANDS relies on bioequivalence/comparative studies).
const FEES: { fy: string; review: number; rts: number }[] = [
  { fy: "2025-26", review: 70750, rts: 5531 },
  { fy: "2026-27", review: 71953, rts: 5626 },
];

const cad = (n: number) =>
  n.toLocaleString("en-CA", { style: "currency", currency: "CAD",
    maximumFractionDigits: 0 });

export function CostTimelineAnchor() {
  const [open, setOpen] = useState(false);
  return (
    <section className="card glass" aria-label="Typical ANDS cost and timeline"
      style={{ padding: "12px 16px", marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
        flexWrap: "wrap" }}>
        <Landmark size={15} aria-hidden />
        <b style={{ fontSize: 14 }}>Where you stand — typical ANDS cost &amp;
          timeline</b>
        <span className="mut" style={{ fontSize: 12 }}>
          Health Canada Fees Order figures + service standards
        </span>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button className="ghost" aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          style={{ fontSize: 12, display: "inline-flex", alignItems: "center",
            gap: 4 }}>
          {open ? <ChevronDown size={14} aria-hidden />
            : <ChevronRight size={14} aria-hidden />}
          {open ? "Hide" : "Show"}
        </button>
      </div>

      {open && (
        <div style={{ marginTop: 10, display: "grid", gap: 10,
          maxWidth: "88ch" }}>
          <div>
            <b style={{ fontSize: 13 }}>Health Canada fees (the same figures
              the in-app fee engine applies)</b>
            <ul className="mut" style={{ fontSize: 12.5, margin: "4px 0 0",
              paddingLeft: 18, lineHeight: 1.6 }}>
              {FEES.map((f) => (
                <li key={f.fy}>
                  <b>{f.fy}</b>: ANDS review fee {cad(f.review)} (Schedule 1,
                  comparative-studies grouping) · Right-to-Sell {cad(f.rts)}
                  {" "}per DIN per year (due Oct 1, after NOC).
                </li>
              ))}
              <li>
                Small business (SME): 50% review-fee remission — or a 100%
                waiver on your first-ever submission — but SME status must be
                granted by Health Canada <b>before</b> you file.
              </li>
            </ul>
            <p className="mut" style={{ fontSize: 12, margin: "4px 0 0" }}>
              Fees are CPI-indexed every April 1 — verify the current Fees
              Order figure before budgeting. Not included above: your own
              development/BE-study and preparation costs, which typically
              dwarf the filing fee.
            </p>
          </div>
          <div>
            <b style={{ fontSize: 13 }}>Typical timeline (service standards,
              not guarantees)</b>
            <ul className="mut" style={{ fontSize: 12.5, margin: "4px 0 0",
              paddingLeft: 18, lineHeight: 1.6 }}>
              <li>Enrolment: Company ID via REP — lead time ~2 weeks; the
                Dossier ID Request rides on the same enrolment (start early;
                you can build against a placeholder meanwhile).</li>
              <li>Screening after filing: ~45 days (completeness check — an
                SDN gives 45 days to fix gaps).</li>
              <li>Science review for an ANDS: ~180 days performance standard,
                longer if an NON/NOD response cycle is needed.</li>
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}
