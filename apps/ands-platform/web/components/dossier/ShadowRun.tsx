"use client";
// CAMP-SHADOW — the shadow / parallel-run affordance (de-risk the trial).
//
// A hands-on task-based usability eval found the single most-common thing a
// regulatory buyer said before trusting the tool live (16/24 task-eval
// personas): "before I trust it live I would run it in parallel against a
// filing we KNOW passed eValidator and diff the tool's output against our
// validated publisher's output." This makes that a first-class in-app
// affordance.
//
// It runs ANDS Studio's OWN structural validator + import-compatibility
// self-check over a prior/known-good sequence and lays the result out
// diff-friendly: structural verdict, a leaf inventory (leaf_id / href / md5 /
// operation), lifecycle operations, and package inventory — so the filer can
// line the tool's view up against their validated publisher's output. When the
// filer pastes a known-good REFERENCE leaf list (what their publisher's
// validator enumerated — leaf_id / href / checksum) the tool computes a
// leaf-level DIFF: matched / checksum-mismatch / only-in-tool / only-in-ref.
//
// HONEST: this is a confidence-building comparison of STRUCTURAL output, NOT a
// guarantee the sequence will pass Health Canada's official eValidator, and it
// never drives the filing gate. The backend rides that disclaimer on the
// report; it is rendered verbatim here.
import { useCallback, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import { toast } from "sonner";
import {
  GitCompareArrows,
  CheckCircle2,
  XCircle,
  Play,
  FileClock,
  ListTree,
  ScanSearch,
  AlertTriangle,
  Equal,
} from "lucide-react";
import type {
  ShadowRunReport,
  ShadowReferenceLeaf,
} from "@/lib/dossierTypes";

function shortHash(md5: string): string {
  if (!md5) return "—";
  return md5.length > 12 ? `${md5.slice(0, 8)}…${md5.slice(-4)}` : md5;
}

// Parse a pasted known-good reference. Accepts either a JSON array of
// {leaf_id, href, checksum} rows, or a whitespace/newline-tolerant paste. We
// keep it forgiving but explicit: only these three fields are used.
function parseReference(raw: string): ShadowReferenceLeaf[] {
  const text = raw.trim();
  if (!text) return [];
  const data = JSON.parse(text);
  const rows = Array.isArray(data)
    ? data
    : Array.isArray((data as { leaves?: unknown[] })?.leaves)
    ? (data as { leaves: unknown[] }).leaves
    : null;
  if (!rows) {
    throw new Error(
      "Expected a JSON array of leaves — [{ leaf_id, href, checksum }, …]."
    );
  }
  return rows.map((r) => {
    const o = (r ?? {}) as Record<string, unknown>;
    const leaf_id = String(o.leaf_id ?? o.leafId ?? o.id ?? "").trim();
    if (!leaf_id) {
      throw new Error("Every reference leaf needs a leaf_id.");
    }
    return {
      leaf_id,
      href: o.href != null ? String(o.href).trim() : undefined,
      checksum:
        o.checksum != null
          ? String(o.checksum).trim()
          : o.md5 != null
          ? String(o.md5).trim()
          : undefined,
    };
  });
}

export function ShadowRun({
  dossierId,
  sequence = "0000",
}: {
  dossierId: string;
  sequence?: string;
}) {
  const [report, setReport] = useState<ShadowRunReport | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showRef, setShowRef] = useState(false);
  const [refText, setRefText] = useState("");

  const run = useCallback(
    (reference?: ShadowReferenceLeaf[]) => {
      setLoading(true);
      setError("");
      dossierApi
        .shadowRun(dossierId, sequence, reference)
        .then((r) => {
          setReport(r);
          if (r.has_reference && r.diff) {
            r.diff.identical
              ? toast.success(
                  "Shadow run: the tool's leaf view matches your known-good reference."
                )
              : toast.warning(
                  "Shadow run complete — differences found. Review the diff below."
                );
          } else {
            toast.success(
              `Shadow run complete over sequence ${r.sequence}.`
            );
          }
        })
        .catch((e) => {
          setError(String(e));
          toast.error(`Shadow run failed — ${String(e)}`);
        })
        .finally(() => setLoading(false));
    },
    [dossierId, sequence]
  );

  const runWithReference = useCallback(() => {
    let ref: ShadowReferenceLeaf[];
    try {
      ref = parseReference(refText);
    } catch (e) {
      toast.error(`Could not read the reference — ${String(e)}`);
      return;
    }
    if (ref.length === 0) {
      toast.error("Paste at least one known-good reference leaf.");
      return;
    }
    run(ref);
  }, [refText, run]);

  const diff = report?.diff ?? null;

  return (
    <div className="card glass" style={{ marginTop: 10 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <GitCompareArrows size={18} aria-hidden />
          <b>Shadow / parallel run</b>
          {report && (
            <span
              className={`notice ${report.validation.passed ? "ok" : "bad"}`}
              role="status"
              style={{
                fontSize: 11,
                padding: "1px 8px",
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              {report.validation.passed ? (
                <CheckCircle2 size={13} aria-hidden />
              ) : (
                <XCircle size={13} aria-hidden />
              )}
              {report.validation.passed
                ? "Structural checks pass"
                : "Structural findings"}
            </span>
          )}
        </div>
        <button
          className="chip"
          onClick={() => run()}
          disabled={loading}
          title="Run ANDS Studio's structural validator + import-compat self-check over this sequence, laid out so you can diff it against a filing you know passed eValidator"
          style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
        >
          <Play size={12} aria-hidden />
          {loading ? "Running…" : report ? "Re-run" : "Run shadow"}
        </button>
      </div>

      <p className="mut" style={{ fontSize: 12, marginTop: 6 }}>
        Before you trust ANDS Studio live, run it in parallel against a filing
        you <b>know</b> passed your validated publisher / Health&nbsp;Canada&apos;s
        eValidator. This runs the same structural validator + import-compat
        self-check over sequence {report?.sequence || sequence} and lays the
        result out so you can diff the tool&apos;s view against your publisher&apos;s
        output — leaf by leaf.
      </p>

      {error && (
        <div className="notice bad" style={{ marginTop: 8, fontSize: 12 }}>
          {error}
        </div>
      )}

      {report && (
        <>
          {/* headline: three legible signals to line up against the publisher */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
              gap: 8,
              marginTop: 10,
            }}
          >
            <Signal
              ok={report.validation.passed}
              icon={<ScanSearch size={14} aria-hidden />}
              label="Structural validation"
              value={
                report.validation.passed
                  ? "Passes"
                  : `${report.validation.errors.length} finding(s)`
              }
            />
            <Signal
              ok={report.import_compat.compatible}
              icon={<CheckCircle2 size={14} aria-hidden />}
              label="Import compatibility"
              value={
                report.import_compat.compatible
                  ? "Compatible"
                  : "Not compatible"
              }
            />
            <Signal
              neutral
              icon={<ListTree size={14} aria-hidden />}
              label="Leaves shipped"
              value={String(report.leaf_count)}
            />
          </div>

          {/* the diff-friendly leaf inventory — what the filer lines up */}
          <details style={{ marginTop: 10 }} open={!report.has_reference}>
            <summary
              style={{
                cursor: "pointer",
                fontSize: 12,
                display: "flex",
                gap: 6,
                alignItems: "center",
              }}
            >
              <ListTree size={14} aria-hidden />
              Leaf inventory — line this up against your publisher (
              {report.leaf_inventory.length})
            </summary>
            <div style={{ overflowX: "auto", marginTop: 8 }}>
              <table
                style={{
                  fontSize: 11,
                  borderCollapse: "collapse",
                  width: "100%",
                  minWidth: 520,
                }}
              >
                <thead>
                  <tr className="mut" style={{ textAlign: "left" }}>
                    <Th>leaf_id</Th>
                    <Th>op</Th>
                    <Th>href</Th>
                    {/* ROUND9-VALIDATE item 16 (consultant_ex_hc): the md5
                        column is labeled document control — enforced by the
                        copy-rule lint in the service suite. */}
                    <Th>
                      <span title="content fingerprint for document control — NOT validation or acceptance">
                        md5 (document control)
                      </span>
                    </Th>
                  </tr>
                </thead>
                <tbody>
                  {report.leaf_inventory.map((lf, i) => (
                    <tr
                      key={`${lf.leaf_id}-${i}`}
                      style={{ borderTop: "1px solid var(--hair, #e5e5e5)" }}
                    >
                      <Td>
                        <code>{lf.leaf_id}</code>
                      </Td>
                      <Td>
                        <code>{lf.operation || "new"}</code>
                      </Td>
                      <Td>
                        <span className="mut">{lf.href || "—"}</span>
                      </Td>
                      <Td>
                        <code title={lf.md5}>{shortHash(lf.md5)}</code>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>

          {/* lifecycle operations, in order */}
          {report.lifecycle_operations.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary
                style={{
                  cursor: "pointer",
                  fontSize: 12,
                  display: "flex",
                  gap: 6,
                  alignItems: "center",
                }}
              >
                <FileClock size={14} aria-hidden />
                Lifecycle operations ({report.lifecycle_operations.length})
              </summary>
              <ul
                style={{
                  margin: "6px 0 0",
                  paddingLeft: 18,
                  fontSize: 11,
                  lineHeight: 1.7,
                }}
              >
                {report.lifecycle_operations.map((op, i) => (
                  <li key={`${op.leaf_id}-${i}`}>
                    <code>{op.operation || "new"}</code> {op.leaf_id}
                    {op.modified_leaf && (
                      <span className="mut"> → {op.modified_leaf}</span>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {/* the leaf-level DIFF against a known-good reference, when supplied */}
          {report.has_reference && diff && (
            <div
              className={`notice ${diff.identical ? "ok" : "bad"}`}
              style={{ marginTop: 10, fontSize: 12 }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  fontWeight: 600,
                }}
              >
                {diff.identical ? (
                  <Equal size={15} aria-hidden />
                ) : (
                  <AlertTriangle size={15} aria-hidden />
                )}
                {diff.identical
                  ? "Identical — the tool's leaf view matches your known-good reference"
                  : "Differences found — reconcile before you trust it live"}
              </div>
              <div className="mut" style={{ marginTop: 4 }}>
                {diff.matched_count} matched · {diff.checksum_mismatch.length}{" "}
                checksum-mismatch · {diff.only_in_tool.length} only-in-tool ·{" "}
                {diff.only_in_reference.length} only-in-reference (tool{" "}
                {diff.tool_leaf_count} / reference {diff.reference_leaf_count})
              </div>

              {diff.checksum_mismatch.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <b>Checksum mismatch</b> (both sides shipped this leaf, bytes
                  differ):
                  <ul style={{ margin: "3px 0 0", paddingLeft: 18 }}>
                    {diff.checksum_mismatch.map((m) => (
                      <li key={m.leaf_id}>
                        <code>{m.leaf_id}</code> — tool{" "}
                        <code>{shortHash(m.tool_md5 || "")}</code> vs reference{" "}
                        <code>{shortHash(m.reference_checksum || "")}</code>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {diff.only_in_tool.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <b>Only in the tool&apos;s view:</b>{" "}
                  {diff.only_in_tool.map((r) => r.leaf_id).join(", ")}
                </div>
              )}
              {diff.only_in_reference.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <b>Only in your reference:</b>{" "}
                  {diff.only_in_reference.map((r) => r.leaf_id).join(", ")}
                </div>
              )}
            </div>
          )}

          {/* paste a known-good reference to drive the leaf-level diff */}
          <div style={{ marginTop: 10 }}>
            <button
              className="chip"
              onClick={() => setShowRef((v) => !v)}
              style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
            >
              <GitCompareArrows size={12} aria-hidden />
              {showRef
                ? "Hide known-good reference"
                : "Diff against a known-good reference…"}
            </button>
            {showRef && (
              <div style={{ marginTop: 8 }}>
                <p className="mut" style={{ fontSize: 11 }}>
                  Paste the leaf list your validated publisher / eValidator
                  enumerated for a filing you <b>know</b> passed — a JSON array
                  of <code>{"{ leaf_id, href, checksum }"}</code>. The tool
                  diffs its own leaf view against it. Only these three fields
                  are read; nothing is transmitted.
                </p>
                <textarea
                  value={refText}
                  onChange={(e) => setRefText(e.target.value)}
                  placeholder={
                    '[{ "leaf_id": "m1-0-1-cover-letter", "href": "m1/ca/…", "checksum": "…" }]'
                  }
                  spellCheck={false}
                  style={{
                    width: "100%",
                    minHeight: 90,
                    marginTop: 6,
                    fontFamily: "var(--mono, ui-monospace, monospace)",
                    fontSize: 11,
                    padding: 8,
                    borderRadius: 6,
                    border: "1px solid var(--hair, #d0d0d0)",
                    background: "var(--panel, transparent)",
                    resize: "vertical",
                  }}
                />
                <button
                  className="chip"
                  onClick={runWithReference}
                  disabled={loading}
                  style={{
                    marginTop: 6,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  <GitCompareArrows size={12} aria-hidden />
                  {loading ? "Diffing…" : "Run shadow diff"}
                </button>
              </div>
            )}
          </div>

          {/* honesty: a confidence-building comparison, NOT a guarantee */}
          <div
            className="mut"
            style={{
              marginTop: 10,
              fontSize: 11,
              opacity: 0.85,
              lineHeight: 1.5,
            }}
          >
            {report.disclaimer}
          </div>
        </>
      )}
    </div>
  );
}

function Signal({
  ok,
  neutral,
  icon,
  label,
  value,
}: {
  ok?: boolean;
  neutral?: boolean;
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  const color = neutral
    ? "var(--fg, inherit)"
    : ok
    ? "var(--ok, #2e7d32)"
    : "var(--bad, #c62828)";
  return (
    <div
      className="notice"
      style={{ padding: "8px 10px", display: "grid", gap: 2 }}
    >
      <div
        className="mut"
        style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 4 }}
      >
        {icon}
        {label}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th style={{ padding: "2px 8px 4px 0", fontWeight: 600 }}>{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td style={{ padding: "3px 8px 3px 0", verticalAlign: "top" }}>{children}</td>;
}
