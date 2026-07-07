"use client";
// Round-9 (operations BLOCKER, n=4): "I need it to reconcile against the real
// DIN/Right-to-Sell status and my actual filed sequences, otherwise it's a
// parallel truth that drifts."
//
// A compact per-clock control: record the date you VERIFIED against the
// external source of truth (HC correspondence, Vault RIM, the filed
// sequence), with who/when/source captured append-only on the lifecycle
// service. A verified value that differs from the calculated one is flagged,
// never hidden. CONFLICT RULE (stated in-UI): the externally verified date
// governs your decisions; the calculated value stays displayed for
// traceability — this tool never overwrites the official record.
import { useState } from "react";
import { lifecycleApi, today, type VerifiedDate } from "./api";

export function VerifiedDateControl({
  dossierId,
  clockKey,
  calculated,
  latest,
  onSaved,
}: {
  dossierId: string;
  clockKey: string;
  // the currently-calculated date this clock shows (ISO), if any
  calculated?: string | null;
  // the latest verification for this clock (parent fetches per dossier)
  latest?: VerifiedDate | null;
  onSaved?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState("");
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // drift: the clock was recalculated since the verification was recorded
  const drift =
    latest && calculated && latest.calculated_date &&
    latest.calculated_date !== calculated;

  async function save() {
    setBusy(true);
    setErr("");
    try {
      await lifecycleApi.setVerifiedDate({
        dossier_id: dossierId,
        clock_key: clockKey,
        verified_date: date,
        calculated_date: calculated || undefined,
        source_ref: source,
      });
      setOpen(false);
      setSource("");
      onSaved?.();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4,
      flexWrap: "wrap", fontSize: 11 }}>
      {latest && (
        <span
          className={`chip ${latest.discrepancy || drift ? "blocked" : "ready"}`}
          style={{ fontSize: 10.5 }}
          title={
            `Verified ${latest.verified_date} by ${latest.verified_by || "unrecorded"} · ` +
            `${latest.verified_at.slice(0, 16).replace("T", " ")} UTC · ` +
            `source: ${latest.source_ref}` +
            (latest.discrepancy
              ? ` · DIFFERS from the calculated ${latest.calculated_date} — the ` +
                `verified date governs; correct the underlying record`
              : "") +
            (drift
              ? ` · the calculated value has CHANGED since this verification ` +
                `(was ${latest.calculated_date}, now ${calculated}) — re-verify`
              : "") +
            (latest.history_count && latest.history_count > 1
              ? ` · ${latest.history_count} verifications on record (append-only)`
              : "")
          }
        >
          {latest.discrepancy || drift ? "⚠" : "✓"} verified {latest.verified_date}
          {latest.discrepancy ? " ≠ calculated" : drift ? " · stale" : ""}
        </span>
      )}
      <button
        className="ghost"
        style={{ fontSize: 10.5, padding: "1px 6px" }}
        aria-expanded={open}
        title="Record the date you verified against the external source of truth (HC letter, Vault RIM, filed sequence). Recorded append-only with who/when/source."
        onClick={() => {
          setOpen((v) => !v);
          if (!open) setDate(latest?.verified_date || calculated || today());
        }}
      >
        {latest ? "Re-verify" : "Verify date"}
      </button>
      {open && (
        <span className="notice" style={{ display: "inline-flex", gap: 6,
          alignItems: "center", flexWrap: "wrap", padding: "6px 8px",
          fontSize: 11 }}>
          <input type="date" value={date} style={{ width: "auto" }}
            aria-label="Externally verified date"
            onChange={(e) => setDate(e.target.value)} />
          <input value={source} style={{ width: 220 }}
            aria-label="Source reference for this verification"
            placeholder="Source (HC letter ref, Vault RIM record…)"
            onChange={(e) => setSource(e.target.value)} />
          <button disabled={busy || !date || !source.trim()} onClick={save}
            style={{ fontSize: 11 }}>
            {busy ? "Recording…" : "Record"}
          </button>
          {err && <span className="mut" style={{ color: "var(--warn)" }}>{err}</span>}
        </span>
      )}
    </span>
  );
}
