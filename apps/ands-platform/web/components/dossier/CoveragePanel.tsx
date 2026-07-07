"use client";
// Round-9 builder_forms MAJOR "No pricing/coverage clarity vs consultant for
// solo filers" (n=2; startup_founder): an HONEST coverage-and-cost panel for
// the builder rail.
//
// HONESTY BAR (hard): no published per-seat / per-dossier plan pricing exists,
// so none is invented — the panel states the self-hosted reality plainly. The
// consultant figure is labelled as the evaluation panel's own benchmark, not a
// market fact. The "consultant review" escape hatch is a real hand-off pack
// (pre-flight report + validation exports from the Application Viewer) — we do
// NOT broker consultants and the panel says so.
import Link from "next/link";
import { Scale } from "lucide-react";

export function CoveragePanel({ dossierId }: { dossierId: string }) {
  return (
    <div style={{ fontSize: 12, lineHeight: 1.55 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <Scale size={14} aria-hidden />
        <b>What this tool covers — and what still lands on you</b>
      </div>

      <div className="mut" style={{ marginTop: 6, fontWeight: 600 }}>
        Covered here
      </div>
      <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
        <li>eCTD structure, backbone XML (index.xml + ca-regional.xml) and sequence export</li>
        <li>Bilingual EN/FR Product Monograph tracking + XML PM build &amp; validate</li>
        <li>Structural completeness checks with a versioned, cited rule catalogue</li>
        <li>Live HC fee calculation (Fees Order figures) on the fee step (1.2.2)</li>
        <li>Part-11 audit trail, e-signature and provenance labelling</li>
      </ul>

      <div className="mut" style={{ marginTop: 8, fontWeight: 600 }}>
        Still on you (or your consultant)
      </div>
      <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
        <li>The scientific / bioequivalence content itself and its expert review</li>
        <li>Running Health Canada&apos;s official eValidator before you transmit</li>
        <li>French translation quality review of labelling content</li>
        <li>CESG trading-partner account and the actual transmission</li>
        <li>QA sign-off wherever your own SOPs require it</li>
      </ul>

      <div className="mut" style={{ marginTop: 8, fontWeight: 600 }}>
        Cost, stated honestly
      </div>
      <p style={{ margin: "4px 0 0" }}>
        ANDS Studio is self-hosted — there is <b>no published per-seat or
        per-dossier price today</b>; your platform cost is your own
        infrastructure plus your licence agreement. Health Canada&apos;s fees
        are computed live on the fee step from the current Fees Order.
        Our evaluation panel benchmarked a full-service consultant ANDS
        engagement at roughly $180k — treat your own quotes as the real
        number; this tool covers the structural, publishing and tracking share
        of that scope, not the scientific content work.
      </p>

      <div className="mut" style={{ marginTop: 8, fontWeight: 600 }}>
        Consultant review — hand-off pack
      </div>
      <p style={{ margin: "4px 0 0" }}>
        Want an independent expert pass? Export the pre-flight report and the
        validation CSV/JSON from the{" "}
        <Link href={`/dossiers/${encodeURIComponent(dossierId)}/viewer`}>
          Application Viewer
        </Link>{" "}
        and hand them to a consultant of your choosing. ANDS Studio does not
        broker or sell consultant services.
      </p>
    </div>
  );
}
