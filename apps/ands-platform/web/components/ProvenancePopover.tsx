"use client";
// WS3 day-counter provenance: a click/hover popover attached to any day-counter
// (45-day NOA window, 24-month stay, NOA/Right-to-Sell clocks) that states, for
// record integrity, exactly HOW a displayed number was arrived at:
//   - the anchor date and its SOURCE (ingested notice vs hand-keyed)
//   - the counting basis (calendar days vs business days)
//   - the counting rule, with a Health Canada / PM(NOC) citation
//   - the governing instrument + clause the citation derives from
//   - the source correspondence / date the value ultimately derives from
//   - a stamped "calculated aid — verify against the HC record" caveat
// It fabricates no legal dates: every field is passed in from data the
// lifecycle service already returns.
//
// WS-OPS-PROV (Round-8 BLOCKER, n=14): the panel asked that EVERY computed
// clock carry (a) the source CITATION — the governing instrument and clause,
// stated faithfully, never a fabricated clause number — AND (b) the source
// correspondence / date the value derives from, plus a "calculated aid — verify
// against the HC record" caveat stamped on the clock itself. Two optional
// fields (`instrument`, `derivedFrom`) and a standing caveat badge carry that,
// backward-compatibly for existing consumers.
import { AlertTriangle, ScrollText } from "lucide-react";
import { useState } from "react";

export type Provenance = {
  anchorLabel: string;         // e.g. "NOA served"
  anchorDate: string | null;   // the real anchor date (from lifecycle)
  anchorSource: "ingested" | "hand-keyed"; // how the anchor got here
  basis: "calendar" | "business"; // day-counting basis
  rule: string;                // the counting rule in words
  citation: string;            // HC / PM(NOC) citation (instrument + clause)
  asOf?: string | null;        // the date the count was computed against
  // WS-OPS-PROV: the governing regulatory INSTRUMENT the citation lives in,
  // stated faithfully. Where an exact clause is not pinned with confidence, the
  // instrument alone is cited (e.g. "PM(NOC) Regulations") — never an invented
  // clause number. Optional so existing callers keep compiling.
  instrument?: string;
  // WS-OPS-PROV: the source CORRESPONDENCE / RECORD the value derives from — the
  // served notice, HC letter or operator entry that fixed the anchor date — so a
  // reviewer can trace the number back to a real document, not just a rule.
  derivedFrom?: {
    label: string;             // e.g. "NOA served on the innovator"
    date?: string | null;      // the date on that record
    source?: string;           // where it came from (e.g. "operator-entered")
  } | null;
};

// The standing caveat stamped on every computed clock. Kept as one shared
// string so the wording the panel asked for is identical on every surface.
export const CLOCK_CAVEAT =
  "Calculated aid — verify against the HC record.";

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
        aria-label="How is this counted? Show provenance and citation"
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
            width: 340,
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

            {/* WS-OPS-PROV: source citation — the governing instrument + clause. */}
            <Row k="Citation">
              <span style={{ display: "inline-flex", gap: 6, alignItems: "flex-start" }}>
                <ScrollText size={13} style={{ flexShrink: 0, marginTop: 2 }} aria-hidden />
                <span>
                  {prov.citation}
                  {prov.instrument && (
                    <span className="mut" style={{ display: "block", marginTop: 2 }}>
                      Governing instrument: {prov.instrument}
                    </span>
                  )}
                </span>
              </span>
            </Row>

            {/* WS-OPS-PROV: the source correspondence / record the value derives
                from — so the number traces back to a real document. */}
            {prov.derivedFrom && (
              <Row k="Derived from">
                {prov.derivedFrom.label}
                {prov.derivedFrom.date ? ` — ${prov.derivedFrom.date}` : ""}
                {prov.derivedFrom.source && (
                  <span className="mut" style={{ display: "block", marginTop: 2 }}>
                    {prov.derivedFrom.source}
                  </span>
                )}
              </Row>
            )}
          </div>

          {/* WS-OPS-PROV: the stamped caveat the panel asked for, on every
              clock. Rendered as an at-a-glance badge, not buried footnote text. */}
          <div
            className="notice warn"
            style={{
              marginTop: 8,
              padding: "7px 10px",
              fontSize: 11,
              display: "flex",
              gap: 7,
              alignItems: "flex-start",
            }}
          >
            <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} aria-hidden />
            <span>
              <b>{CLOCK_CAVEAT}</b> This is a computed value — confirm the anchor
              date against the served notice / HC record and the governing
              regulation before relying on it for a filing or litigation deadline.
            </span>
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
