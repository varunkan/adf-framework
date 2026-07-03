"use client";
// WS3 day-counter provenance: a click/hover popover attached to any day-counter
// (45-day NOA window, 24-month stay, NOA/Right-to-Sell clocks) that states, for
// record integrity, exactly HOW a displayed number was arrived at:
//   - the anchor date and its SOURCE (ingested notice vs hand-keyed)
//   - the counting basis (calendar days vs business days)
//   - the counting rule, with a Health Canada / PM(NOC) citation
//   - a standing "computed — verify independently" disclaimer
// It fabricates no legal dates: every field is passed in from data the
// lifecycle service already returns.
import { useState } from "react";

export type Provenance = {
  anchorLabel: string;         // e.g. "NOA served"
  anchorDate: string | null;   // the real anchor date (from lifecycle)
  anchorSource: "ingested" | "hand-keyed"; // how the anchor got here
  basis: "calendar" | "business"; // day-counting basis
  rule: string;                // the counting rule in words
  citation: string;            // HC / PM(NOC) citation
  asOf?: string | null;        // the date the count was computed against
};

export function ProvenancePopover({ prov }: { prov: Provenance }) {
  const [open, setOpen] = useState(false);
  return (
    <span
      style={{ position: "relative", display: "inline-flex" }}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="ghost"
        aria-label="How is this counted? Show provenance"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={() => setOpen(true)}
        style={{ fontSize: 11, padding: "0 5px", lineHeight: 1.4, cursor: "help" }}
      >
        ⓘ prov
      </button>
      {open && (
        <div
          role="tooltip"
          className="card glass"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            marginTop: 6,
            width: 320,
            maxWidth: "80vw",
            padding: 12,
            zIndex: 50,
            fontSize: 12,
            lineHeight: 1.5,
            textAlign: "left",
          }}
        >
          <div style={{ display: "grid", gap: 6 }}>
            <Row k="Anchor">
              {prov.anchorLabel}
              {prov.anchorDate ? ` — ${prov.anchorDate}` : " — (not yet set)"}
            </Row>
            <Row k="Anchor source">
              {prov.anchorSource === "ingested"
                ? "ingested from a served notice"
                : "hand-keyed by a user"}
            </Row>
            <Row k="Basis">
              {prov.basis === "calendar"
                ? "calendar days (weekends/holidays counted)"
                : "business days (HC working days)"}
            </Row>
            {prov.asOf && <Row k="Counted as of">{prov.asOf}</Row>}
            <Row k="Rule">{prov.rule}</Row>
            <Row k="Citation">{prov.citation}</Row>
          </div>
          <div
            className="mut"
            style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--line)" }}
          >
            Computed value — verify independently against the served notice and
            the governing regulation before relying on it for a filing or
            litigation deadline.
          </div>
        </div>
      )}
    </span>
  );
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <span className="mut" style={{ minWidth: 92, flexShrink: 0 }}>
        {k}
      </span>
      <span>{children}</span>
    </div>
  );
}
