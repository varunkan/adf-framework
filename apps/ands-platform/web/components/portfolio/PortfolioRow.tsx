"use client";
// One dossier in the CRO portfolio: identity, module tower, gate, fees, links.
import Link from "next/link";
import type { DossierListItem } from "@/lib/dossierTypes";
import type { DossierTaskSummary } from "@/lib/collabApi";
import { MiniTower } from "./MiniTower";
import { ProvenancePopover, type Provenance } from "@/components/ProvenancePopover";
import { dueMeta } from "@/lib/deadline";

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
      <div title="Client / sponsor company (REP identity)">
        <span className="mut">Client </span>
        {sponsor || <span className="mut">—</span>}
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

  return (
    <div
      className="card glass"
      style={{
        padding: "14px 18px",
        display: "flex",
        alignItems: "center",
        gap: 18,
        flexWrap: "wrap",
      }}
    >
      <div style={{ flex: "1 1 220px", minWidth: 200 }}>
        <div className="d-id">{d.dossier_id}</div>
        <div className="d-title" style={{ margin: "2px 0 0" }}>{d.title}</div>
        <div className="d-meta mut">
          {d.submission_type}
          {d.cs_be_only ? " · CS-BE" : ""}
        </div>
      </div>

      {/* WS6 PM columns: owner / client / soonest deadline, at a glance */}
      <PmColumns owner={d.owner} sponsor={d.sponsor} due={d.soonest_due} />

      <MiniTower tower={d.tower} missing={d.gate?.missing} />

      <span className={`chip ${d.gate?.complete ? "ready" : "blocked"}`}>
        {d.gate?.complete ? "Ready to file" : `${passed}/${applic} modules`}
      </span>

      <FeeChip state={fee} />
      <NoaChip clock={noa} />
      <CollabChips collab={collab} />

      <span style={{ display: "flex", gap: 8 }}>
        <Link className="chip" href={`/dossiers/${id}/m/1`}
          aria-label={`Open dossier ${d.dossier_id}`}>
          Open →
        </Link>
        <Link className="chip" href={`/dossiers/${id}/viewer`}
          aria-label={`Open Application Viewer for ${d.dossier_id}`}>
          Viewer
        </Link>
      </span>
    </div>
  );
}
