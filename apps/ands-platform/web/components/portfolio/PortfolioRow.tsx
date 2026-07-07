"use client";
// One dossier in the CRO portfolio: identity, module tower, gate, fees, links.
import Link from "next/link";
import type { DossierListItem } from "@/lib/dossierTypes";
import type { DossierTaskSummary } from "@/lib/collabApi";
import { MiniTower } from "./MiniTower";
import { ProvenancePopover, type Provenance } from "@/components/ProvenancePopover";
import { dueMeta } from "@/lib/deadline";
import { ShieldCheck } from "lucide-react";
import { Term } from "@/components/Term";

export type FeeState =
  | { kind: "loading" }
  | { kind: "unknown" }
  | { kind: "paid" }
  | { kind: "waived" }
  | { kind: "due"; amount: number; currency: string };

// live PM(NOC) clock on a served Form V allegation, from the lifecycle service.
// WS3: each clock carries its PROVENANCE so a displayed day-count can be traced
// to the anchor date, its source and the counting rule (record integrity — a
// regulatory deadline number must never be an unexplained figure on screen).
export type NoaClock =
  | { kind: "none" }
  | { kind: "action"; days: number; prov: Provenance }  // brand's 45-day window
  | { kind: "stay"; days: number; prov: Provenance };   // 24-month stay running

function NoaChip({ clock }: { clock: NoaClock }) {
  if (clock.kind === "none") return null;
  const urgent = clock.days <= 10;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
      <span className={`chip ${urgent ? "blocked" : ""}`}
        title={clock.kind === "action"
          ? "A Notice of Allegation is served — days left in the brand's 45-day window to start litigation"
          : "PM(NOC) 24-month stay is running — days until it lapses"}>
        ⏱ {clock.kind === "action"
          ? `NOA: ${clock.days}d for brand to act`
          : `stay: ${clock.days}d remaining`}
      </span>
      <ProvenancePopover prov={clock.prov} />
    </span>
  );
}

function FeeChip({ state }: { state: FeeState }) {
  switch (state.kind) {
    case "loading":
      return null;  // no placeholder flicker — the chip appears once resolved
    case "paid":
      return <span className="chip ready">Fee paid</span>;
    case "waived":
      return <span className="chip ready">Fee waived</span>;
    case "due":
      return (
        <span className="chip blocked">
          Fee due {state.amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {state.currency}
        </span>
      );
    default:
      return <span className="chip mut" aria-label="Fee status unavailable">Fee —</span>;
  }
}

// WS6: owner (accountable PM) · client (REP sponsor) · soonest deadline. A PM
// scanning the portfolio sees ownership and client segregation without opening
// a dossier. Missing values read as an explicit "—" (unassigned), never blank.
function PmColumns({ owner, sponsor, due }: {
  owner?: string | null; sponsor?: string | null; due?: string | null }) {
  const dm = dueMeta(due);
  return (
    <div style={{ flex: "0 1 220px", minWidth: 160, display: "flex",
      flexDirection: "column", gap: 2, fontSize: 12 }}>
      <div title="Accountable owner (project manager)">
        <span className="mut">Owner </span>
        <b>{owner || "—"}</b>
      </div>
      {/* WS-OPS-TENANT: per-sponsor access indicator at the row level — a
          shield beside the client name makes the per-sponsor data boundary
          legible while scanning. Honest scope: workspace isolation is the
          API-enforced wall; this marks which client the row belongs to. */}
      <div title="Client / sponsor company (REP identity) — records scoped to this sponsor">
        <span className="mut">Client </span>
        {sponsor ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <ShieldCheck size={11} aria-hidden style={{ opacity: 0.7 }} />
            {sponsor}
          </span>
        ) : (
          <span className="mut">—</span>
        )}
      </div>
      <div title="Soonest content-plan deadline">
        <span className="mut">Due </span>
        {dm ? (
          <span className={`chip ${dm.overdue || dm.days <= 7 ? "blocked" : ""}`}
            style={{ fontSize: 11 }}>
            {dm.iso} · {dm.label}
          </span>
        ) : (
          <span className="mut">none set</span>
        )}
      </div>
    </div>
  );
}

// WS7: who is assigned + whether the dossier is blocked, from the collaboration
// service's open-task roll-up. Absent = no open tasks (or collab offline) — the
// column simply doesn't render; never a fabricated status.
function CollabChips({ collab }: { collab?: DossierTaskSummary }) {
  if (!collab || collab.open === 0) return null;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4,
      flexWrap: "wrap" }}>
      {collab.blocked && (
        <span className="chip blocked" style={{ fontSize: 11 }}
          title={`${collab.overdue} open task(s) past due`}>
          ⛔ blocked
        </span>
      )}
      <span className="chip" style={{ fontSize: 11 }}
        title={`${collab.open} open task(s) — assigned to ${collab.assignees.join(", ")}`}>
        👤 {collab.assignees.length === 1
          ? collab.assignees[0]
          : `${collab.assignees.length} assignees`} · {collab.open} open
      </span>
    </span>
  );
}

export function PortfolioRow({ d, fee, noa = { kind: "none" }, collab }: {
  d: DossierListItem; fee: FeeState; noa?: NoaClock;
  collab?: DossierTaskSummary }) {
  const passed = d.tower.filter((t) => t.state === "pass").length;
  const applic = d.tower.filter((t) => t.state !== "na").length;
  const id = encodeURIComponent(d.dossier_id);
  // Round-9 (operations, n=3+6): at-risk states surface at ROW level; neutral
  // states stay in Details (the progressive disclosure the panel praised).
  const overdue = dueMeta(d.soonest_due)?.overdue ?? false;
  const blockedAndOverdue = Boolean(collab?.blocked) && overdue;
  const urgentNoa = noa.kind !== "none" && noa.days <= 10;

  return (
    <div className="card glass roster-row portfolio-row">
      {/* col 1 — identity (truncates, never widens the column) */}
      <div>
        <div className="d-id">{d.dossier_id}</div>
        <div className="d-title" style={{ margin: "2px 0 0" }}>{d.title}</div>
        <div className="d-meta mut">
          <Term k={d.submission_type}>{d.submission_type}</Term>
          {d.cs_be_only ? <> · <Term k="CS-BE" /></> : null}
        </div>
      </div>

      {/* col 2 — WS6 PM columns: owner / client / soonest deadline */}
      <PmColumns owner={d.owner} sponsor={d.sponsor} due={d.soonest_due} />

      {/* col 3 — module tower (fills the cell, right-aligned bars) */}
      <MiniTower tower={d.tower} missing={d.gate?.missing} />

      {/* col 4 — ONE primary status chip, in a fixed-width cell so every row's
          status aligns. Blocked collaboration outranks the gate. Round-9: the
          blocked REASON is inline (no Details hunt), blocked+past-deadline is
          a distinct combined state, and the tooltip states the exact rule that
          trips each state — including that "Ready to file" reflects internal
          module completeness, NOT an eValidator pass. */}
      <span className="roster-status">
        <span
          className={`chip ${
            collab?.blocked ? "blocked" : d.gate?.complete ? "ready" : "blocked"
          }`}
          style={blockedAndOverdue ? { fontWeight: 700 } : undefined}
          title={
            collab?.blocked
              ? `Rule: an open collaboration task is past its due date (${collab.overdue} overdue, assigned to ${collab.assignees.join(", ") || "unassigned"}). Outranks the module gate.`
              : d.gate?.complete
                ? "Rule: every applicable module has its required documents placed. Internal completeness only — NOT an eValidator or Health Canada validation pass; run validation before relying on this."
                : "Rule: one or more applicable modules still have required documents outstanding."
          }
        >
          {blockedAndOverdue
            ? "Blocked & past due"
            : collab?.blocked
              ? `Blocked — ${collab.overdue} task(s) overdue`
              : d.gate?.complete
                ? "Ready to file"
                : `${passed}/${applic} modules`}
        </span>
        {/* at-risk statutory clock escapes the Details expander (n=6:
            "statutory clocks are not an advanced afterthought") */}
        {urgentNoa && <NoaChip clock={noa} />}
      </span>

      {/* col 5 — actions: details expander + Open/Viewer, right-aligned */}
      <div className="roster-actions">
        <details className="row-details">
          <summary aria-label={`Show fee, litigation and collaboration detail for ${d.dossier_id}`}>
            Details
          </summary>
          <div className="row-details-body">
            <FeeChip state={fee} />
            {/* non-urgent clocks stay here; urgent ones are on the row face */}
            {!urgentNoa && <NoaChip clock={noa} />}
            <CollabChips collab={collab} />
          </div>
        </details>
        <Link className="chip" href={`/dossiers/${id}/m/1`}
          aria-label={`Open dossier ${d.dossier_id}`}>
          Open →
        </Link>
        <Link className="chip" href={`/dossiers/${id}/viewer`}
          aria-label={`Open Application Viewer and eCTD validation for ${d.dossier_id}`}
          title="index.xml backbone, eCTD validation, eValidator handoff and the pre-flight report live here">
          Viewer · validation
        </Link>
      </div>
    </div>
  );
}
