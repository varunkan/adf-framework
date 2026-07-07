"use client";
// journey · J12 cost & time visibility (round-9 MAJOR, n=3; cdmo_ra_manager,
// startup_founder): "nowhere in this journey do I see time or money".
//
// HONEST SUBSET (stated in-UI): this card shows the pieces that are REAL —
// the live HC fee tally recorded at the fees step and a hedged steps/weeks
// readout from HC's published service standards. ANDS Studio has NO published
// per-seat / per-dossier price list, so no platform dollar figure is invented
// here — pricing is quoted per deployment, and the card says so flatly.
import { Coins } from "lucide-react";
import type { JourneyView } from "@/lib/types";
import { citeLine, LAST_VERIFIED, type RegCitation } from "@/lib/regCitations";

// HC review service standards (screening / ANDS review targets) — hedged
// targets, not promises. Kept as a local citation so the wording carries the
// shared "last verified" stamp from lib/regCitations (read-only import).
const REVIEW_TARGETS: RegCitation = {
  claim:
    "Screening target ~45 calendar days; ANDS review target ~180 days. " +
    "These are Health Canada service standards, not guarantees — the clock " +
    "counts HC's time only and pauses while HC waits on you.",
  source:
    "Health Canada — Guidance: Management of Drug Submissions and " +
    "Applications (performance standards)",
  verified: LAST_VERIFIED,
};

function fmtCad(n: number): string {
  try {
    return new Intl.NumberFormat("en-CA", {
      style: "currency",
      currency: "CAD",
      maximumFractionDigits: 0,
    }).format(n);
  } catch {
    return `$${Math.round(n)} CAD`;
  }
}

export function CostTimeCard({ view }: { view: JourneyView }) {
  const fees = (view.signals || {}).fees as
    | {
        paid?: boolean;
        sme_granted?: boolean;
        fiscal_year?: string;
        amount?: number;
        payable?: number;
        real?: boolean;
      }
    | undefined;
  const stepsLeft = Math.max(0, view.readiness.total - view.readiness.done);
  const transmitted = view.readiness.transmitted;

  return (
    <div className="card glass" style={{ marginTop: 12, padding: 14 }}>
      <div
        className="eyebrow"
        style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}
      >
        <Coins size={13} aria-hidden />
        Cost &amp; time
      </div>

      {/* time: a hedged steps/weeks readout, never a promise */}
      <div style={{ fontSize: 13 }}>
        {transmitted ? (
          <>
            <b>Filed.</b> Health Canada&apos;s review clock is running — track
            it on the final step.
          </>
        ) : (
          <>
            <b>
              {stepsLeft} of {view.readiness.total} filing steps left
            </b>{" "}
            before you can transmit.
          </>
        )}
      </div>
      <p className="mut" style={{ fontSize: 12, margin: "6px 0 0" }}>
        After you file: screening targets <b>~45 days</b> and the ANDS science
        review targets <b>~180 days</b> — Health Canada service standards, not
        guarantees; actual timelines vary and the clock pauses while HC waits
        on you.
      </p>
      <p className="mut" style={{ fontSize: 10.5, margin: "4px 0 0" }}>
        {citeLine(REVIEW_TARGETS)}
      </p>

      {/* money: the REAL HC fee tally recorded at the fees step */}
      <div
        style={{
          marginTop: 10,
          paddingTop: 10,
          borderTop: "1px solid var(--line)",
          fontSize: 13,
        }}
      >
        <b>Health Canada fees</b>
        {fees ? (
          <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
            ANDS review fee{fees.fiscal_year ? ` (${fees.fiscal_year})` : ""}:{" "}
            <b>
              {typeof fees.amount === "number" ? fmtCad(fees.amount) : "recorded"}
            </b>
            {typeof fees.payable === "number" &&
              fees.payable !== fees.amount && (
                <>
                  {" "}
                  · payable after mitigation: <b>{fmtCad(fees.payable)}</b>
                </>
              )}
            {fees.sme_granted ? " · small-business reduction applied" : ""}
            {fees.paid ? " · confirmed" : ""}
          </div>
        ) : (
          <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
            Computed live at the <b>Pay the fees</b> step for the current
            fiscal year (re-indexed every April 1) — no memorized figure is
            shown here.
          </div>
        )}
      </div>

      {/* platform pricing: the flat, honest statement — nothing invented */}
      <div
        className="mut"
        style={{
          marginTop: 10,
          paddingTop: 10,
          borderTop: "1px solid var(--line)",
          fontSize: 11.5,
          lineHeight: 1.5,
        }}
      >
        <b>Platform pricing:</b> ANDS Studio has no published per-seat or
        per-dossier price list today — pricing is quoted per deployment.
        We state that plainly rather than showing an invented number.
      </div>
    </div>
  );
}
