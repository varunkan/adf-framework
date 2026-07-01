"use client";
import { useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { ValidationResult } from "@/lib/dossierTypes";

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
  const v = full || structural;

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
      {v.errors.slice(0, 5).map((e, i) => (
        <div key={i} className="mut" style={{ fontSize: 12, marginTop: 3 }}>
          • {e.message}
        </div>
      ))}
      {v.warnings.length > 0 && (
        <div className="mut" style={{ fontSize: 11, marginTop: 4 }}>
          {v.warnings.length} warning(s)
        </div>
      )}
      <button className="ghost" style={{ marginTop: 10, fontSize: 12, padding: "6px 10px" }}
        onClick={run} disabled={busy}>
        {busy ? "Checking…" : "Run full check (PDF conformance)"}
      </button>
    </div>
  );
}
