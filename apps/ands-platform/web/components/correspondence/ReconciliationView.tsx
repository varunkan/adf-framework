"use client";
// Round-9 (operations BLOCKER, n=4): the reconciliation view — tool dates vs
// the externally recorded official values, side by side, with an explicit
// rule for which wins on conflict. HONEST SCOPE: reconciliation is
// manual-entry based — there is no live Vault RIM / Health Canada feed; the
// source you cite is recorded verbatim on the append-only verification log.
import { useCallback, useEffect, useState } from "react";
import { lifecycleApi, type NoaRecord, type VerifiedDate } from "./api";
import { VerifiedDateControl } from "./VerifiedDate";

// current calculated value for a clock_key, resolved from the live NOA list.
// rts:* keys are registry-side clocks — their current value renders on the
// Registry page; here we show the value captured at verification time.
function currentCalculated(key: string, noas: NoaRecord[]): string | null {
  const m = key.match(/^noa:([^:]+):(action_window|stay)$/);
  if (!m) return null;
  const n = noas.find((x) => x.id === m[1]);
  if (!n) return null;
  return (m[2] === "action_window" ? n.action_window_end : n.stay_end) || null;
}

function keyLabel(key: string, noas: NoaRecord[]): string {
  const m = key.match(/^noa:([^:]+):(action_window|stay)$/);
  if (m) {
    const n = noas.find((x) => x.id === m[1]);
    const what = m[2] === "action_window"
      ? "45-day action window end" : "24-month stay end";
    return n ? `Patent ${n.patent_number} — ${what}` : key;
  }
  const r = key.match(/^rts:[^:]+:(.+)$/);
  if (r) return `Right-to-Sell due (FY ${r[1]}) — see Registry page`;
  return key;
}

export function ReconciliationView({ dossierId }: { dossierId: string }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<VerifiedDate[] | null>(null);
  const [noas, setNoas] = useState<NoaRecord[]>([]);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const [v, n] = await Promise.all([
        lifecycleApi.listVerifiedDates(dossierId),
        lifecycleApi.listNoa(dossierId).catch(() => ({ allegations: [] })),
      ]);
      setRows(v.verifications);
      setNoas(n.allegations);
    } catch (e) {
      setErr(String(e));
      setRows([]);
    }
  }, [dossierId]);

  useEffect(() => {
    if (open && rows === null) load();
  }, [open, rows, load]);

  return (
    <div className="card glass" style={{ padding: 0 }}>
      <button
        className="ghost"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={{ width: "100%", textAlign: "left", padding: "12px 18px",
          fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}
      >
        <span>{open ? "▾" : "▸"}</span>
        Reconciliation — tool dates vs your verified official values
        <span className="mut" style={{ fontWeight: 400, fontSize: 12 }}>
          calculated vs externally verified, discrepancies flagged
        </span>
      </button>
      {open && (
        <div style={{ padding: "0 18px 16px", display: "grid", gap: 10 }}>
          <p className="mut" style={{ margin: 0, fontSize: 12, maxWidth: "80ch" }}>
            <b>Which wins on conflict:</b> the externally verified date governs
            your decisions — correct the underlying record to match the official
            source; the calculated value stays displayed for traceability and is
            never silently overwritten. <b>Honest scope:</b> reconciliation is
            manual — there is no live Vault RIM / Health Canada feed. The source
            reference you cite is recorded verbatim, append-only, with who and
            when.
          </p>
          {err && <div className="notice bad" style={{ fontSize: 12 }}>{err}</div>}
          {rows === null ? (
            <div className="mut" style={{ fontSize: 12 }}>Loading…</div>
          ) : rows.length === 0 ? (
            <div className="mut" style={{ fontSize: 12 }}>
              No verified dates recorded for this dossier yet. Use “Verify
              date” beside any statutory clock (here or on the Registry page)
              to record the value you confirmed against the official source.
            </div>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0,
              display: "grid", gap: 8, fontSize: 12 }}>
              {rows.map((v) => {
                const current = currentCalculated(v.clock_key, noas);
                const drift = current && v.calculated_date &&
                  current !== v.calculated_date;
                return (
                  <li key={v.id} className="card" style={{ padding: "8px 12px",
                    display: "flex", gap: 10, flexWrap: "wrap",
                    alignItems: "baseline" }}>
                    <b style={{ minWidth: 220 }}>{keyLabel(v.clock_key, noas)}</b>
                    <span className="mut">
                      calculated {v.calculated_date || "—"}
                      {drift ? ` (now ${current})` : ""}
                    </span>
                    <span>verified <b>{v.verified_date}</b></span>
                    {(v.discrepancy || drift) && (
                      <span className="chip blocked" style={{ fontSize: 10.5 }}
                        title={v.discrepancy
                          ? "The verified date differs from the calculated one — the verified date governs; correct the underlying record"
                          : "The calculated value changed after this verification — re-verify against the official source"}>
                        {v.discrepancy ? "⚠ discrepancy" : "⚠ re-verify (drifted)"}
                      </span>
                    )}
                    <span className="mut" style={{ flexBasis: "100%" }}>
                      by {v.verified_by || "unrecorded"} ·{" "}
                      {v.verified_at.slice(0, 16).replace("T", " ")} UTC ·
                      source: {v.source_ref}
                      {v.history_count && v.history_count > 1
                        ? ` · ${v.history_count} verifications (append-only)`
                        : ""}
                    </span>
                    <VerifiedDateControl
                      dossierId={dossierId}
                      clockKey={v.clock_key}
                      calculated={current || v.calculated_date}
                      latest={v}
                      onSaved={load}
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
