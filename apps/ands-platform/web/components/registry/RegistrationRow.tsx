"use client";
// One registration: product × country × dossier × DIN, status chip and the
// transitions the service's state machine allows from here.
import Link from "next/link";
import {
  TRANSITIONS,
  type Registration,
  type RegistrationStatus,
} from "./registryApi";

function statusChipClass(status: RegistrationStatus): string {
  switch (status) {
    case "NOC-Issued":
    case "Marketed":
      return "chip ready";
    case "Suspended":
      return "chip blocked";
    default:
      return "chip";
  }
}

export function RegistrationRow({
  reg,
  busy,
  onTransition,
}: {
  reg: Registration;
  busy: boolean;
  onTransition: (id: string, status: RegistrationStatus) => void;
}) {
  const next = TRANSITIONS[reg.status] ?? [];
  return (
    <div className="card glass roster-row registry-row">
      {/* col 1 — identity (DIN / product / country · dossier) */}
      <div>
        <div className="d-id">{reg.din || "DIN pending"}</div>
        <div className="d-title" style={{ margin: "2px 0 0" }}>
          {reg.product}
        </div>
        <div className="d-meta mut">
          {reg.country}
          {reg.drug_type ? ` · ${reg.drug_type}` : ""}
          {" · "}
          <Link href={`/dossiers/${encodeURIComponent(reg.dossier_id)}/m/1`}
            aria-label={`Open dossier ${reg.dossier_id}`}>
            {reg.dossier_id}
          </Link>
        </div>
        {/* TIER-B: honest note that a disinfectant/biocide DIN is NNHPD-assessed,
            NOT an ANDS/NDS eCTD review — so a registry row never implies one. */}
        {reg.regulatory_note && (
          <div className="notice warn"
            style={{ marginTop: 8, fontSize: 12, lineHeight: 1.45 }}>
            {reg.regulatory_note}
          </div>
        )}
      </div>

      {/* col 2 — status chip in a fixed-width cell so every row's status aligns */}
      <span className="roster-status">
        <span className={statusChipClass(reg.status)}>{reg.status}</span>
      </span>

      {/* col 3 — allowed transitions, right-aligned */}
      <div className="roster-actions">
        {next.map((s) => (
          <button key={s} className="chip" disabled={busy}
            onClick={() => onTransition(reg.id, s)}
            aria-label={`Move ${reg.product} to ${s} — records the status only, does not file with Health Canada`}
            title={`Records this status in your workspace only — it does not file or transmit anything to Health Canada. Set it to mirror what Health Canada has told you.`}>
            → {s}
          </button>
        ))}
        {next.length === 0 && (
          <span className="chip mut">No further transitions</span>
        )}
      </div>
    </div>
  );
}
