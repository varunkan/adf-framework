"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { dossierApi } from "@/lib/dossierApi";
import { opMeta } from "@/lib/leafStatus";
import { ChipLegend } from "./ChipLegend";
import {
  indexRules,
  moduleOfLeaf,
  modulePath,
  ruleForFinding,
  ruleHowToFix,
} from "./validationExtras";
import type {
  CurrentView,
  CurrentViewLeaf,
  ExportValidationVerdict,
  SequenceInfo,
  SequenceList,
  ValidationRule,
} from "@/lib/dossierTypes";

// WS7 — make the new/replace/append/delete lifecycle OPERATOR of each leaf
// visible per sequence. The counts + the modified-leaf back-pointer come from
// the eCTD current view (live set reconstructed from the operations in order).
const OP_LABEL: Record<string, string> = {
  new: "new",
  replace: "replace",
  append: "append",
  delete: "delete",
};

function opsForSequence(view: CurrentView | null, sequence: string): CurrentViewLeaf[] {
  if (!view) return [];
  return [...view.live, ...view.history].filter((l) => l.sequence === sequence);
}

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
export function SequencePanel({
  dossierId,
  onBlockedChange,
}: {
  dossierId: string;
  // Round-6 WS-A: report whether an export-block state is currently active so a
  // collapsing wrapper can keep this panel forced-open (a blocking state must
  // never be hidden behind a collapsed expander).
  onBlockedChange?: (blocked: boolean) => void;
}) {
  const [data, setData] = useState<SequenceList | null>(null);
  const [view, setView] = useState<CurrentView | null>(null);
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
  // ROUND9-VALIDATE item 13 (cro_pm): the per-sequence plain-language rollup —
  // open error/warning counts + last-checked timestamp, from the same
  // structural validator that gates export.
  const [rollups, setRollups] = useState<
    Record<string, { errors: number; warnings: number; at: string }>
  >({});
  // ROUND9-VALIDATE item 14: the live rule catalogue joins each block-modal
  // finding to its how-to-fix hint + owning-module link.
  const [rules, setRules] = useState<ValidationRule[] | null>(null);
  const ruleIdx = useMemo(() => indexRules(rules), [rules]);

  useEffect(() => {
    let live = true;
    dossierApi
      .validationRules()
      .then((c) => {
        if (live) setRules(c.rules);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    let seqs: SequenceInfo[] = [];
    try {
      const list = await dossierApi.listSequences(dossierId);
      setData(list);
      seqs = list.sequences;
      setError("");
    } catch (e) {
      setError(String(e));
    }
    // Operator breakdown is best-effort: a dossier with no eCTD leaves yet has
    // no current view — that must not break the sequence list.
    try {
      setView(await dossierApi.currentView(dossierId));
    } catch {
      setView(null);
    }
    // item 13: per-sequence rollup — best-effort, never blocks the panel.
    try {
      const entries = await Promise.all(
        seqs.map(async (s) => {
          try {
            const r = await dossierApi.validateSequence(dossierId, s.sequence);
            return [
              s.sequence,
              {
                errors: r.errors.length,
                warnings: r.warnings.length,
                at: new Date().toLocaleTimeString(),
              },
            ] as const;
          } catch {
            return null;
          }
        })
      );
      setRollups(
        Object.fromEntries(entries.filter((e): e is NonNullable<typeof e> => !!e))
      );
    } catch {}
  }, [dossierId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // keep the collapsing wrapper informed of the active export-block state
  useEffect(() => {
    onBlockedChange?.(!!block);
  }, [block, onBlockedChange]);

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
        <h3 style={{ margin: 0 }}>Sequences</h3>
        {data && (
          <span className="mut" style={{ marginLeft: "auto", fontSize: 12 }}>
            working: {data.active_sequence}
          </span>
        )}
      </div>
      {/* ROUND9-VALIDATE item 4: the plain-language chip legend lives where
          the chips live. */}
      <ChipLegend compact />
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
              {/* ROUND9-VALIDATE item 3 (n=12): error-severity findings are
                  NEVER truncated — the block modal renders ALL of them. item
                  14: each carries the how-to-fix hint + a 'Fix this' link to
                  the owning module page. */}
              {block.verdict.errors.map((f, i) => {
                const rule = ruleForFinding(ruleIdx, f);
                const hint = ruleHowToFix(rule);
                const mod = moduleOfLeaf(f.leaf, view);
                return (
                  <div key={i} style={{ marginTop: i === 0 ? 0 : 4 }}>
                    <div
                      style={{
                        display: "flex",
                        gap: 6,
                        alignItems: "baseline",
                        flexWrap: "wrap",
                      }}
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
                      {mod && (
                        <Link
                          href={modulePath(dossierId, mod)}
                          className="chip"
                          style={{
                            fontSize: 9,
                            padding: "0 6px",
                            textDecoration: "none",
                          }}
                          title="Open the module page that owns this failing leaf"
                        >
                          Fix this →
                        </Link>
                      )}
                    </div>
                    {hint && (
                      <div
                        className="mut"
                        style={{ fontSize: 10, paddingLeft: 8, marginTop: 1 }}
                      >
                        Fix: {hint}
                      </div>
                    )}
                  </div>
                );
              })}
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

      {data?.sequences.map((s, si) => {
        const ops = opsForSequence(view, s.sequence);
        const counts = ops.reduce<Record<string, number>>((acc, l) => {
          acc[l.operation] = (acc[l.operation] || 0) + 1;
          return acc;
        }, {});
        return (
        <div
          key={s.sequence}
          style={{
            marginTop: si === 0 ? 12 : 12,
            paddingTop: si === 0 ? 0 : 12,
            borderTop: si === 0 ? "none" : "1px solid var(--line)",
          }}
        >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
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
        {/* ROUND9-VALIDATE item 13: the per-sequence plain-language status
            rollup — open error/warning counts + last checked, no rule-id
            decoding needed. */}
        {rollups[s.sequence] && (
          <div className="mut" style={{ fontSize: 10.5, marginTop: 3 }}>
            {rollups[s.sequence].errors} open error(s) ·{" "}
            {rollups[s.sequence].warnings} warning(s) · last checked{" "}
            {rollups[s.sequence].at} (structural check, not HC review)
          </div>
        )}
        {ops.length > 0 && (
          <div
            style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}
            aria-label={`Lifecycle operators in sequence ${s.sequence}`}
          >
            {Object.entries(counts).map(([op, n]) => (
              <span
                key={op}
                className={`chip ${op === "delete" ? "blocked" : ""}`}
                style={{ fontSize: 10 }}
                title={
                  op === "new"
                    ? "New leaf placed in this sequence"
                    : op === "replace"
                      ? "Replaces a leaf from a prior sequence"
                      : op === "append"
                        ? "Appends to a prior leaf"
                        : op === "delete"
                          ? "Retires a leaf from the live view"
                          : op
                }
              >
                {n}× {OP_LABEL[op] || op}
              </span>
            ))}
          </div>
        )}
        {/* ADOPT-LIFECYCLE-0001: a follow-up sequence (0001+) carries the
            lifecycle a response/supplement transaction must ship — every leaf
            that acts on a prior transmitted leaf, with its operation and the
            back-pointer to the leaf it modifies. Render the FULL per-leaf map
            (not a truncated sample) so a publisher can SEE lifecycle
            correctness before transmission, straight from the eCTD backbone. */}
        {(() => {
          const lifecycleLeaves = ops.filter((l) => l.modified_leaf);
          if (lifecycleLeaves.length === 0) return null;
          return (
            <div
              style={{ marginTop: 6, display: "grid", gap: 3 }}
              aria-label={`Lifecycle back-pointers in sequence ${s.sequence}`}
            >
              {lifecycleLeaves.map((l) => {
                const om = opMeta(l.operation);
                return (
                  <div
                    key={l.leaf_id}
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      gap: 6,
                      fontSize: 10,
                    }}
                    title={
                      `${l.operation} — this sequence's leaf ${l.leaf_id} ` +
                      `acts on prior leaf ${l.modified_leaf}. The backbone XML ` +
                      `records a <modified-file> back-pointer at the prior ` +
                      `leaf's relative path, so Health Canada's reviewer ` +
                      `replays the lifecycle against the right document.`
                    }
                  >
                    <span className={om?.risk ? "t-op warn" : "t-op"}>
                      {om?.label || l.operation.toUpperCase()}
                    </span>
                    <code style={{ fontSize: 10 }}>{l.leaf_id}</code>
                    <span className="mut" aria-hidden>
                      →
                    </span>
                    <code
                      className="mut"
                      style={{ fontSize: 10 }}
                      title={`prior leaf superseded: ${l.modified_leaf}`}
                    >
                      {l.modified_leaf}
                    </code>
                  </div>
                );
              })}
            </div>
          );
        })()}
        </div>
        );
      })}
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
