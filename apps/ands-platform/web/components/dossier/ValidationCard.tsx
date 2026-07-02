"use client";
import { useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { ValidationResult } from "@/lib/dossierTypes";

type Finding = ValidationResult["errors"][number];

// One validation finding, labeled with its HC-style rule ID — regulatory
// operations people reason in rule IDs, not prose.
function Row({ f, warn }: { f: Finding; warn?: boolean }) {
  return (
    <div className="mut" style={{ fontSize: 12, marginTop: 3, display: "flex",
      gap: 6, alignItems: "baseline" }}>
      <code style={{ fontSize: 10, opacity: 0.85, whiteSpace: "nowrap" }}>
        {f.rule_id || (warn ? "CA-W" : "CA-E")}
      </code>
      <span>
        {f.message}
        {f.leaf ? <i style={{ opacity: 0.7 }}> — {f.leaf}</i> : null}
      </span>
    </div>
  );
}

// Shows the structural eCTD validation from content-state, with a button to run
// the FULL technical validation (incl. PDF conformance on the stored bytes).
export function ValidationCard({
  dossierId,
  structural,
}: {
  dossierId: string;
  structural: ValidationResult;
}) {
  const [full, setFull] = useState<ValidationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const v = full || structural;
  const errs = showAll ? v.errors : v.errors.slice(0, 5);

  async function run() {
    setBusy(true);
    try {
      setFull(await dossierApi.validate(dossierId));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <div className="mut" style={{ fontSize: 12 }}>eCTD validation</div>
        <span style={{ marginLeft: "auto" }}
          className={`ready-status ${v.passed ? "READY" : "BLOCKED"}`}>
          {v.passed ? "● PASSED" : `● ${v.errors.length} error(s)`}
        </span>
      </div>
      {errs.map((e, i) => <Row key={i} f={e} />)}
      {v.errors.length > 5 && (
        <button className="ghost" style={{ fontSize: 11, padding: "2px 6px" }}
          onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Show fewer" : `Show all ${v.errors.length} errors`}
        </button>
      )}
      {(showAll ? v.warnings : v.warnings.slice(0, 3)).map((w, i) => (
        <Row key={`w${i}`} f={w} warn />
      ))}
      {v.warnings.length > 3 && !showAll && (
        <div className="mut" style={{ fontSize: 11, marginTop: 4 }}>
          +{v.warnings.length - 3} more warning(s) — Show all above
        </div>
      )}
      <button className="ghost" style={{ marginTop: 10, fontSize: 12, padding: "6px 10px" }}
        onClick={run} disabled={busy}>
        {busy ? "Checking…" : "Run full check (PDF conformance)"}
      </button>
      <div className="mut" style={{ fontSize: 10, marginTop: 6 }}>
        Findings carry Health Canada eCTD validation-rule-style IDs
        (CA-E-…/CA-W-…) covering leaf integrity, lifecycle legality, naming,
        sequence numbering, XML backbone and PDF conformance.
      </div>
    </div>
  );
}
