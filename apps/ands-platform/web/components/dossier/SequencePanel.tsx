"use client";
import { useCallback, useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { SequenceInfo, SequenceList } from "@/lib/dossierTypes";

const PURPOSES = [
  { value: "response", label: "Response" },
  { value: "supplement", label: "Supplement" },
  { value: "annual-notification", label: "Annual notification" },
  { value: "initial", label: "Initial" },
];
const PURPOSE_LABEL: Record<string, string> = Object.fromEntries(
  PURPOSES.map((p) => [p.value, p.label])
);

function nextSequence(seqs: SequenceInfo[]): string {
  const nums = seqs
    .map((s) => parseInt(s.sequence, 10))
    .filter((n) => !Number.isNaN(n));
  const next = nums.length ? Math.max(...nums) + 1 : 0;
  return String(next).padStart(4, "0");
}

// Sidebar card: the dossier's eCTD sequences — which one is the ACTIVE
// working sequence (new placements land there), each one's regulatory
// purpose, plus per-sequence export of the transmissible package.
export function SequencePanel({ dossierId }: { dossierId: string }) {
  const [data, setData] = useState<SequenceList | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [purpose, setPurpose] = useState("response");
  const [note, setNote] = useState("");

  const refresh = useCallback(async () => {
    try {
      setData(await dossierApi.listSequences(dossierId));
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }, [dossierId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function create() {
    if (!data) return;
    setBusy(true);
    try {
      setData(
        await dossierApi.createSequence(dossierId, {
          sequence: nextSequence(data.sequences),
          purpose,
          note,
        })
      );
      setNote("");
      setCreating(false);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function activate(sequence: string) {
    setBusy(true);
    try {
      setData(await dossierApi.activateSequence(dossierId, sequence));
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <div className="mut" style={{ fontSize: 12 }}>Sequences</div>
        {data && (
          <span className="mut" style={{ marginLeft: "auto", fontSize: 11 }}>
            working: {data.active_sequence}
          </span>
        )}
      </div>
      {error && (
        <div className="notice bad" style={{ marginTop: 8, fontSize: 12 }}>
          {error}
        </div>
      )}
      {data?.sequences.map((s) => (
        <div
          key={s.sequence}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginTop: 8,
            fontSize: 12,
          }}
        >
          <span style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
            {s.sequence}
          </span>
          <span className="chip" title={s.note || undefined}>
            {PURPOSE_LABEL[s.purpose] || s.purpose}
          </span>
          <span className="mut">{s.leaf_count} leaf(s)</span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            {s.active ? (
              <span className="ready-status READY" style={{ fontSize: 11 }}>
                ● ACTIVE
              </span>
            ) : (
              <button
                className="ghost"
                style={{ fontSize: 11, padding: "3px 8px" }}
                onClick={() => activate(s.sequence)}
                disabled={busy}
              >
                Make active
              </button>
            )}
            <a
              className="chip"
              href={dossierApi.exportUrl(dossierId, s.sequence)}
              title={`Download the eCTD package for sequence ${s.sequence}`}
              onClick={async (e) => {
                // don't hand over a package screening would bounce — check
                // validation first and make an un-validated export explicit
                e.preventDefault();
                const href = dossierApi.exportUrl(dossierId, s.sequence);
                try {
                  const v = await dossierApi.validate(dossierId);
                  if (
                    v.passed ||
                    window.confirm(
                      `Validation has ${v.errors.length} unresolved error(s)` +
                      (v.errors[0] ? ` (e.g. ${(v.errors[0] as any).rule_id ||
                        v.errors[0].rule}: ${v.errors[0].message})` : "") +
                      ".\n\nHealth Canada screening would reject this " +
                      "package. Export anyway for internal review?")
                  ) window.location.assign(href);
                } catch {
                  window.location.assign(href); // validator offline — export
                }
              }}
            >
              Export
            </a>
          </span>
        </div>
      ))}
      {creating && data ? (
        <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
          <div className="mut" style={{ fontSize: 12 }}>
            New sequence {nextSequence(data.sequences)}
          </div>
          <select
            aria-label="Sequence purpose"
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            style={{ fontSize: 12, padding: "7px 9px" }}
          >
            {PURPOSES.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
          <input
            aria-label="Sequence note"
            placeholder="Note (e.g. screening deficiency SDN-1)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            style={{ fontSize: 12, padding: "7px 9px" }}
          />
          <div style={{ display: "flex", gap: 6 }}>
            <button
              style={{ fontSize: 12, padding: "6px 10px" }}
              onClick={create}
              disabled={busy}
            >
              {busy ? "Creating…" : "Create & make active"}
            </button>
            <button
              className="ghost"
              style={{ fontSize: 12, padding: "6px 10px" }}
              onClick={() => setCreating(false)}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          className="ghost"
          style={{ marginTop: 10, fontSize: 12, padding: "6px 10px" }}
          onClick={() => setCreating(true)}
          disabled={!data || busy}
        >
          New sequence
        </button>
      )}
    </div>
  );
}
