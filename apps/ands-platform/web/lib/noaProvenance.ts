// WS3 day-counter provenance (record integrity).
//
// A single pure function that turns the lifecycle service's NOA allegation
// records into the portfolio-row day-counter (`NoaClock`) — carrying, for every
// displayed number, the PROVENANCE the reviewer needs to trust or refute it:
//   - the anchor date and where it came from (a served notice, hand-keyed by an
//     operator on the /noa/{id}/serve or /action call)
//   - the counting basis (the PM(NOC) windows are CALENDAR days)
//   - the counting rule in words, with a PM(NOC) Regulations citation
//   - the as-of date the count was computed against
//
// It FABRICATES no legal dates: every field is read off the lifecycle record
// (served_date, action_window_end, action_date, stay_end, as_of). If the anchor
// date is absent the popover shows "(not yet set)" rather than inventing one.
//
// Kept as a pure module (no React) so the derivation is unit-checkable and the
// UI wiring stays a thin render.
import type { NoaClock } from "@/components/portfolio/PortfolioRow";
import type { Provenance } from "@/components/ProvenancePopover";

// The relevant subset of one lifecycle NOA allegation record (see
// services/lifecycle/app/noa.py :: with_clocks).
export type NoaRecord = {
  status?: string;
  served_date?: string | null;
  action_window_end?: string | null;
  action_date?: string | null;
  stay_start?: string | null;
  stay_end?: string | null;
  as_of?: string | null;
  action_days_remaining?: number | null;
  stay_days_remaining?: number | null;
};

// s.6(1): the innovator's 45 CALENDAR-day window to commence an action, counted
// from the date the NOA was served. Served date is operator-entered (hand-keyed
// on /noa/{id}/serve), so it is labelled as such — not passed off as ingested.
export function actionProvenance(rec: NoaRecord): Provenance {
  return {
    anchorLabel: "NOA served",
    anchorDate: rec.served_date ?? null,
    anchorSource: "hand-keyed",
    basis: "calendar",
    rule:
      "45 calendar days are added to the service date to fix the end of the " +
      "innovator's window to commence a s.6 action.",
    citation: "PM(NOC) Regulations, s.6(1) (45-day action window)",
    asOf: rec.as_of ?? null,
  };
}

// s.7(1)(d): the 24-month statutory stay runs from the date the s.6 action was
// commenced. That commencement date is likewise operator-entered.
export function stayProvenance(rec: NoaRecord): Provenance {
  return {
    anchorLabel: "s.6 action commenced",
    anchorDate: rec.action_date ?? rec.stay_start ?? null,
    anchorSource: "hand-keyed",
    basis: "calendar",
    rule:
      "24 months are added to the action-commencement date (end-of-month " +
      "clamped) to fix the statutory-stay expiry.",
    citation: "PM(NOC) Regulations, s.7(1)(d) (24-month stay)",
    asOf: rec.as_of ?? null,
  };
}

// Reduce every allegation on a dossier to the single most-pressing clock, with
// its provenance. Mirrors the prior inline logic in portfolio/page.tsx exactly:
// a served allegation with days left => the action clock; a running stay => the
// stay clock. Absent either, the row shows no clock.
export function noaClockFrom(records: NoaRecord[]): NoaClock {
  let clock: NoaClock = { kind: "none" };
  for (const n of records || []) {
    if (n.status === "served" && (n.action_days_remaining ?? 0) > 0) {
      clock = {
        kind: "action",
        days: n.action_days_remaining as number,
        prov: actionProvenance(n),
      };
    } else if (n.status === "stay_running" && (n.stay_days_remaining ?? 0) > 0) {
      clock = {
        kind: "stay",
        days: n.stay_days_remaining as number,
        prov: stayProvenance(n),
      };
    }
  }
  return clock;
}
