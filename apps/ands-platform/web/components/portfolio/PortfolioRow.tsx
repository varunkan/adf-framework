"use client";
// One dossier in the CRO portfolio: identity, module tower, gate, fees, links.
import Link from "next/link";
import type { DossierListItem } from "@/lib/dossierTypes";
import { MiniTower } from "./MiniTower";

export type FeeState =
  | { kind: "loading" }
  | { kind: "unknown" }
  | { kind: "paid" }
  | { kind: "waived" }
  | { kind: "due"; amount: number; currency: string };

// live PM(NOC) clock on a served Form V allegation, from the lifecycle service
export type NoaClock =
  | { kind: "none" }
  | { kind: "action"; days: number }    // brand's 45-day window to litigate
  | { kind: "stay"; days: number };     // 24-month stay running

function NoaChip({ clock }: { clock: NoaClock }) {
  if (clock.kind === "none") return null;
  const urgent = clock.days <= 10;
  return (
    <span className={`chip ${urgent ? "blocked" : ""}`}
      title={clock.kind === "action"
        ? "A Notice of Allegation is served — days left in the brand's 45-day window to start litigation"
        : "PM(NOC) 24-month stay is running — days until it lapses"}>
      ⏱ {clock.kind === "action"
        ? `NOA: ${clock.days}d for brand to act`
        : `stay: ${clock.days}d remaining`}
    </span>
  );
}

function FeeChip({ state }: { state: FeeState }) {
  switch (state.kind) {
    case "loading":
      return <span className="chip mut" aria-label="Fee status loading">Fee …</span>;
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

export function PortfolioRow({ d, fee, noa = { kind: "none" } }: {
  d: DossierListItem; fee: FeeState; noa?: NoaClock }) {
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

      <MiniTower tower={d.tower} />

      <span className={`chip ${d.gate?.complete ? "ready" : "blocked"}`}>
        {d.gate?.complete ? "Ready to file" : `${passed}/${applic} modules`}
      </span>

      <FeeChip state={fee} />
      <NoaChip clock={noa} />

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
