"use client";
import { useCallback, useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type {
  ExportValidationVerdict,
  SequenceInfo,
  SequenceList,
} from "@/lib/dossierTypes";

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
  // Export gate: when the backend fails closed (409), we hold the blocking
  // verdict + the sequence it belongs to so the modal can show the findings
  // and offer an explicit, reasoned override.
  const [block, setBlock] = useState<{
    sequence: string;
    verdict?: ExportValidationVerdict;
    title: string;
    detail?: string;
  } | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [exporting, setExporting] = useState("");

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

  function saveBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // Export fails CLOSED: on 409 we surface the blocking findings + criteria in
  // a modal rather than silently downloading an unfileable package or letting
  // the browser navigate to the JSON error.
  async function exportSeq(
    sequence: string,
    opts: { override?: boolean; reason?: string } = {}
  ) {
    setExporting(sequence);
    setError("");
    try {
      const out = await dossierApi.exportSequence(dossierId, sequence, opts);
      if (out.ok) {
        saveBlob(out.blob, out.filename);
        setBlock(null);
        setOverrideReason("");
      } else {
        setBlock({
          sequence,
          verdict: out.validation,
          title: out.title,
          detail: out.detail,
        });
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setExporting("");
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

      {block && (
        <div
          className="notice bad"
          style={{ marginTop: 8, fontSize: 12 }}
          role="alertdialog"
          aria-label="Export blocked by validation"
        >
          <div style={{ fontWeight: 700 }}>
            Export blocked — sequence {block.sequence}
          </div>
          <div style={{ marginTop: 4 }}>
            {block.detail ||
              (block.title === "validation_unavailable"
                ? "Validation could not run, so export is blocked."
                : "The completeness check did not pass.")}
          </div>
          {block.verdict?.criteria && (
            <div className="mut" style={{ marginTop: 6, fontSize: 11 }}>
              Checked against {block.verdict.criteria.name} v
              {block.verdict.criteria.version}. This is a structural/format
              check — not a Health Canada review.
            </div>
          )}
          {block.verdict?.errors?.length ? (
            <div style={{ marginTop: 6 }}>
              {block.verdict.errors.slice(0, 8).map((f, i) => (
                <div
                  key={i}
                  style={{ display: "flex", gap: 6, alignItems: "baseline" }}
                >
                  <code style={{ fontSize: 10, whiteSpace: "nowrap" }}>
                    {f.rule_id || f.rule}
                  </code>
                  <span style={{ fontSize: 11 }}>
                    {f.leaf ? (
                      <code style={{ fontSize: 10, opacity: 0.8 }}>
                        {f.leaf}:{" "}
                      </code>
                    ) : null}
                    {f.message}
                  </span>
                </div>
              ))}
              {block.verdict.errors.length > 8 && (
                <div className="mut" style={{ fontSize: 11, marginTop: 3 }}>
                  +{block.verdict.errors.length - 8} more
                </div>
              )}
            </div>
          ) : null}
          <div style={{ marginTop: 10 }}>
            <label
              className="mut"
              style={{ fontSize: 11, display: "block", marginBottom: 4 }}
            >
              To export anyway, type a reason (recorded to the audit trail):
            </label>
            <input
              aria-label="Override reason"
              placeholder="e.g. internal QA review only — not for transmission"
              value={overrideReason}
              onChange={(e) => setOverrideReason(e.target.value)}
              style={{ fontSize: 12, padding: "7px 9px", width: "100%" }}
            />
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              <button
                style={{ fontSize: 12, padding: "6px 10px" }}
                disabled={
                  !overrideReason.trim() || exporting === block.sequence
                }
                onClick={() =>
                  exportSeq(block.sequence, {
                    override: true,
                    reason: overrideReason.trim(),
                  })
                }
              >
                {exporting === block.sequence
                  ? "Exporting…"
                  : "Export anyway (override)"}
              </button>
              <button
                className="ghost"
                style={{ fontSize: 12, padding: "6px 10px" }}
                onClick={() => {
                  setBlock(null);
                  setOverrideReason("");
                }}
              >
                Cancel
              </button>
            </div>
          </div>
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
            <button
              className="chip"
              style={{ fontSize: 11, padding: "3px 8px" }}
              title={`Download the eCTD package for sequence ${s.sequence}`}
              disabled={busy || exporting === s.sequence}
              onClick={() => exportSeq(s.sequence)}
            >
              {exporting === s.sequence ? "Exporting…" : "Export"}
            </button>
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
