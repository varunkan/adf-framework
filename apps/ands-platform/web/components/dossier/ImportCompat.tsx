"use client";
// CAMP-INTEROP — the import-compatibility panel. The one repeated adoption ask
// from regulatory-ops buyers was: "confirm the exported package imports clean
// into our Vault RIM / docuBridge lifecycle." The export IS a genuine ICH eCTD
// 3.2.2 sequence + CA Module 1 v2.2 regional backbone, so ANDS Studio proves it
// by running a STRUCTURAL self-check over the ACTUAL zip it just built and
// surfacing exactly what a compliant RIM importer will find.
//
// HONEST: this verifies the STANDARD structural contract every compliant RIM
// importer relies on. It does NOT certify import into a specific commercial
// system, and it is not Health Canada's official eValidator. Those disclaimers
// ride on the report (from the backend) and are rendered verbatim here.
import { useCallback, useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import {
  PackageCheck,
  CheckCircle2,
  XCircle,
  FileCheck2,
  FileCode2,
  FolderTree,
  RefreshCw,
} from "lucide-react";
import type {
  ImportCompatReport,
  OutlineView,
  ValidationCriteria,
} from "@/lib/dossierTypes";

export function ImportCompat({
  dossierId,
  sequence = "0000",
}: {
  dossierId: string;
  sequence?: string;
}) {
  const [report, setReport] = useState<ImportCompatReport | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  // Round-9 builder_forms BLOCKER "Export/backbone integrity is unverifiable —
  // show real backbone XML, exact checks, byte-true md5" (n=5): the ACTUAL
  // generated backbone XML — index.xml AND ca-regional.xml — inspectable here
  // (fetched lazily when the inspector opens), plus the versioned HC criteria
  // the structural check is modeled on.
  const [outline, setOutline] = useState<OutlineView | null>(null);
  const [outlineErr, setOutlineErr] = useState("");
  const [crit, setCrit] = useState<ValidationCriteria | null>(null);

  useEffect(() => {
    dossierApi
      .criteriaHistory()
      .then((h) => setCrit(h.criteria))
      .catch(() => {});
  }, []);

  const loadOutline = useCallback(() => {
    if (outline) return;
    dossierApi
      .outline(dossierId, sequence)
      .then((o) => {
        setOutline(o);
        setOutlineErr("");
      })
      .catch((e) => setOutlineErr(String(e)));
  }, [dossierId, sequence, outline]);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    dossierApi
      .importCompat(dossierId, sequence)
      .then(setReport)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [dossierId, sequence]);

  useEffect(() => {
    load();
  }, [load]);

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
          <PackageCheck size={18} aria-hidden />
          <h3 style={{ margin: 0 }}>Import compatibility</h3>
          {report && (
            <span
              className={`notice ${report.compatible ? "ok" : "bad"}`}
              role="status"
              style={{
                fontSize: 11,
                padding: "1px 8px",
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              {report.compatible ? (
                <CheckCircle2 size={13} aria-hidden />
              ) : (
                <XCircle size={13} aria-hidden />
              )}
              {report.compatible
                ? `Standard ${report.standard.ectd} structural contract met`
                : `Standard ${report.standard.ectd} structural contract NOT met`}
            </span>
          )}
        </div>
        <button
          className="chip"
          onClick={load}
          disabled={loading}
          title="Re-run the import-compatibility self-check over the exported package"
          style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
        >
          <RefreshCw size={12} aria-hidden />
          {loading ? "Checking…" : "Re-check"}
        </button>
      </div>

      {/* SCOPE — stated next to the verdict so a skimming director cannot
          over-read the green result as "certified into MY Vault instance".
          Prominent (not a footnote) and vendor-neutral. */}
      {report && (
        <div
          className="notice"
          role="note"
          style={{
            marginTop: 8,
            fontSize: 12,
            display: "flex",
            gap: 8,
            alignItems: "flex-start",
            borderLeft: "3px solid var(--brand, #6366f1)",
            fontWeight: 500,
          }}
        >
          <FileCheck2
            size={16}
            aria-hidden
            style={{ flexShrink: 0, marginTop: 1 }}
          />
          <div>
            Verifies the standard structural contract every compliant importer
            relies on. <b>NOT</b> a certified import into a specific system
            (Vault&nbsp;/&nbsp;docuBridge&nbsp;/&nbsp;etc.) — a green result means
            the package meets the {report.standard.ectd} contract, not that it was
            loaded into your Vault instance.
          </div>
        </div>
      )}

      <p className="mut" style={{ fontSize: 12, marginTop: 6 }}>
        A self-check ANDS Studio runs over the eCTD package it just built for
        sequence {report?.sequence || sequence} — the structural contract any
        compliant RIM importer (e.g. Veeva Vault RIM, docuBridge, Lorenz /
        Health&nbsp;Canada eValidator) relies on to load a sequence.
      </p>

      {error && (
        <div className="notice bad" style={{ marginTop: 8, fontSize: 12 }}>
          {error}
        </div>
      )}

      {report && (
        <>
          {/* the standards the importer is being handed — stated plainly */}
          <div
            className="notice"
            style={{
              marginTop: 8,
              fontSize: 12,
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
            }}
          >
            <FileCheck2
              size={16}
              aria-hidden
              style={{ flexShrink: 0, marginTop: 1 }}
            />
            <div>
              This package is a standard <b>{report.standard.ectd}</b> sequence
              with a <b>{report.standard.regional}</b> regional backbone. A
              compliant importer will find exactly this:
            </div>
          </div>

          {/* the per-check structural contract */}
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: "10px 0 0",
              display: "grid",
              gap: 4,
            }}
          >
            {report.checks.map((c) => (
              <li
                key={c.id}
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "flex-start",
                  fontSize: 12,
                }}
              >
                {c.passed ? (
                  <CheckCircle2
                    size={15}
                    aria-hidden
                    className="ok-icon"
                    style={{ flexShrink: 0, marginTop: 1, color: "var(--ok, #2e7d32)" }}
                  />
                ) : (
                  <XCircle
                    size={15}
                    aria-hidden
                    style={{ flexShrink: 0, marginTop: 1, color: "var(--bad, #c62828)" }}
                  />
                )}
                <span>
                  {c.label}
                  {c.detail && (
                    <span className="mut"> — {c.detail}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>

          {/* exactly what an importer will find (inventory) */}
          <details style={{ marginTop: 10 }}>
            <summary
              style={{ cursor: "pointer", fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}
            >
              <FolderTree size={14} aria-hidden />
              What a compliant importer will find ({report.file_count} files)
            </summary>
            <div className="mut" style={{ fontSize: 12, marginTop: 8, lineHeight: 1.7 }}>
              <div>
                <b>Sequence root:</b> <code>{report.inventory.root || "—"}</code>
              </div>
              <div>
                <b>Backbone:</b>{" "}
                <code>{shortName(report.inventory.index_xml)}</code> +{" "}
                <code>{shortName(report.inventory.index_md5)}</code> +{" "}
                <code>{shortName(report.inventory.ca_regional)}</code>
              </div>
              <div>
                <b>util/dtd:</b>{" "}
                {report.inventory.util_dtds.map(shortName).join(", ") || "—"}
              </div>
              <div>
                <b>Modules:</b> {report.inventory.modules.join(", ") || "—"}
              </div>
              {report.leaves.length > 0 && (
                <div style={{ marginTop: 4 }}>
                  <b>Backbone leaves ({report.leaves.length}):</b>
                  <ul style={{ margin: "3px 0 0", paddingLeft: 16 }}>
                    {report.leaves.map((lf, i) => (
                      <li key={`${lf.leaf_id}-${i}`}>
                        <code>{lf.operation || "new"}</code> {lf.href || "(no href)"}
                        {lf.cross_sequence && (
                          <span className="mut"> · cross-sequence ref</span>
                        )}{" "}
                        {lf.resolved ? "✓" : "✗ dangling"}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </details>

          {/* Round-9 builder_forms BLOCKER "Export/backbone integrity is
              unverifiable" (n=5): the real generated backbone XML — BOTH
              index.xml and ca-regional.xml — inspectable in place, so the
              package handed to eValidator can be read line by line. */}
          <details
            style={{ marginTop: 10 }}
            onToggle={(e) => {
              if ((e.currentTarget as HTMLDetailsElement).open) loadOutline();
            }}
          >
            <summary
              style={{ cursor: "pointer", fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}
            >
              <FileCode2 size={14} aria-hidden />
              Inspect the generated backbone XML — index.xml + ca-regional.xml
            </summary>
            {outlineErr && (
              <div className="notice bad" style={{ marginTop: 8, fontSize: 12 }}>
                Backbone unavailable — {outlineErr}
              </div>
            )}
            {!outline && !outlineErr && (
              <div className="mut" style={{ marginTop: 8, fontSize: 12 }}>
                Loading backbone…
              </div>
            )}
            {outline && (
              <div style={{ marginTop: 8 }}>
                <div className="mut" style={{ fontSize: 11, fontWeight: 600 }}>
                  index.xml — ICH eCTD 3.2.2 backbone
                </div>
                <pre
                  className="xml"
                  style={{ maxHeight: 240, overflow: "auto", fontSize: 10.5, marginTop: 4 }}
                >
                  {outline.backbone["index.xml"]}
                </pre>
                <div className="mut" style={{ fontSize: 11, fontWeight: 600, marginTop: 8 }}>
                  ca-regional.xml — CA Module 1 v2.2 regional backbone
                </div>
                <pre
                  className="xml"
                  style={{ maxHeight: 240, overflow: "auto", fontSize: 10.5, marginTop: 4 }}
                >
                  {outline.backbone["ca-regional.xml"]}
                </pre>
                <div className="mut" style={{ fontSize: 11, marginTop: 6 }}>
                  util/dtd ships the DTD set both DOCTYPEs resolve against
                  (ich-ectd-3-2.dtd + ca-regional.dtd) — the files themselves
                  travel inside the exported zip, where they can be inspected
                  byte for byte.
                </div>
              </div>
            )}
          </details>

          {/* Round-9 builder_forms BLOCKER (n=5), profile ask — HONESTY BAR:
              the structural check maps to HC's published criteria at
              rule-family level; NO 1:1 commercial eValidator profile/version
              mapping exists, so none is claimed. */}
          <div className="mut" style={{ marginTop: 10, fontSize: 12, lineHeight: 1.6 }}>
            {crit && (
              <>
                Structural rules: <b>{crit.name} v{crit.version}</b>, modeled on{" "}
                <b>{crit.modeled_on}</b>
                {crit.synced ? <> · synced {crit.synced}</> : null}.{" "}
              </>
            )}
            The check maps to Health Canada&apos;s published criteria at
            rule-family level — it does <b>not</b> map 1:1 to any specific
            commercial eValidator profile/version, so none is claimed here.
            When you run eValidator, select the current Health Canada profile
            inside that tool.
          </div>

          {/* honesty: standard contract, NOT a vendor certification */}
          <div
            className="mut"
            style={{ marginTop: 12, fontSize: 12, opacity: 0.85, lineHeight: 1.6 }}
          >
            {report.disclaimer}
          </div>
        </>
      )}
    </div>
  );
}

function shortName(path: string): string {
  if (!path) return "—";
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}
