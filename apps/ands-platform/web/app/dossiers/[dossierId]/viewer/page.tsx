"use client";
import { useEffect, useState } from "react";
import { useDossier } from "@/components/dossier/DossierContext";
import { dossierApi } from "@/lib/dossierApi";
import { EvalidatorHandoff } from "@/components/dossier/EvalidatorHandoff";
import { ImportCompat } from "@/components/dossier/ImportCompat";
import { ShadowRun } from "@/components/dossier/ShadowRun";
import { PreflightReport } from "@/components/dossier/PreflightReport";
import type { OutlineView } from "@/lib/dossierTypes";

export default function ViewerPage() {
  const { content, loading, dossierId } = useDossier();
  const [tab, setTab] = useState<"files" | "outline">("files");
  const [outline, setOutline] = useState<OutlineView | null>(null);
  const [exportMsg, setExportMsg] = useState("");
  // WS-VALIDATE: on a SUCCESSFUL export, pin the eValidator handoff so the
  // filer never mistakes "package downloaded" for "eValidator-passed".
  const [exportedOk, setExportedOk] = useState(false);
  const [exporting, setExporting] = useState(false);

  // Export fails CLOSED: fetch (not a bare download link) so a 409 shows the
  // reason instead of downloading a JSON error body. Override lives on the
  // dossier's Sequences panel (typed-reason gate) — not offered here.
  async function exportPackage() {
    setExporting(true);
    setExportMsg("");
    setExportedOk(false);
    try {
      const out = await dossierApi.exportSequence(dossierId, "0000");
      if (out.ok) {
        const url = URL.createObjectURL(out.blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = out.filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        setExportedOk(true);
      } else {
        const n = out.validation?.errors?.length ?? 0;
        setExportMsg(
          `Export blocked — the completeness check did not pass` +
            (n ? ` (${n} structural issue(s))` : "") +
            ". Resolve the findings on the module pages, or override with a " +
            "typed reason from the Sequences panel. This structural check is " +
            "not a Health Canada review."
        );
      }
    } catch (e) {
      setExportMsg(String(e));
    } finally {
      setExporting(false);
    }
  }

  useEffect(() => {
    if (tab === "outline" && !outline)
      dossierApi.outline(dossierId).then(setOutline).catch(() => {});
  }, [tab, outline, dossierId]);

  if (loading) return <div className="center mut">Loading…</div>;
  const files = content?.files_view;
  const filled = (files?.nodes || []).filter((n) => n.leaves.length > 0);

  return (
    <main className="viewer">
      <h1>Application Viewer</h1>
      <p className="mut">
        A read-only view of your assembled eCTD — the documents placed under each
        Canadian Module folder, and the backbone outline.
      </p>
      <div className="affordance-bar" role="tablist" aria-label="Viewer">
        <button role="tab" aria-selected={tab === "files"}
          className={tab === "files" ? "on" : ""} onClick={() => setTab("files")}>
          Files
        </button>
        <button role="tab" aria-selected={tab === "outline"}
          className={tab === "outline" ? "on" : ""} onClick={() => setTab("outline")}>
          Outline
        </button>
        <span className="spacer" />
        <button className="chip" onClick={exportPackage} disabled={exporting}
          title="Download the transmissible eCTD package (sequence 0000) — upload it via CESG WebTrader">
          {exporting ? "Exporting…" : "⬇ Export eCTD package"}
        </button>
      </div>
      {exportMsg && (
        <div className="notice bad" style={{ marginTop: 8, fontSize: 12 }}>
          {exportMsg}
        </div>
      )}
      {/* WS-VALIDATE (round-8 blocker, n=12): on export success, pin the
          eValidator handoff — the persistent "run HC eValidator before
          transmission" banner + the parity-gap table — so downloading the
          package is never mistaken for passing HC's official validator. */}
      {exportedOk && (
        <>
          {/* CAMP-INTEROP: the adoption ask — "will this import clean into our
              Vault RIM / docuBridge?". On export success, self-check the exact
              package that was built and show what a compliant importer finds. */}
          <ImportCompat dossierId={dossierId} sequence="0000" />
          {/* CAMP-SHADOW: the trial-de-risking ask — "before I trust it live
              I'd run it in parallel against a filing we KNOW passed eValidator
              and diff the output." A first-class shadow / parallel-run
              affordance over the same known-good sequence. Honest: a
              confidence-building comparison, not a guarantee. */}
          <ShadowRun dossierId={dossierId} sequence="0000" />
          <div className="card glass" style={{ marginTop: 10 }}>
            <div className="mut" style={{ fontSize: 12 }}>
              eCTD package exported. One required step remains before you can
              transmit:
            </div>
            <EvalidatorHandoff criteria={content?.validation?.criteria} />
          </div>
        </>
      )}
      <p className="mut" style={{ fontSize: 12 }}>
        The export is the spec folder tree (index.xml, ca-regional.xml, REP RT
        XML, every leaf at its href with checksums) zipped — what you upload
        through the CESG/FDA-ESG WebTrader.
      </p>

      {/* TIER3-PREFLIGHT: ONE consolidated pre-flight / QA hand-off report —
          the whole filing-readiness picture (structural validation + attested
          eValidator result + Part-11 e-sign + SoD + fees + sequences +
          REP/Dossier-ID) in a single archivable artifact, so a QA reviewer no
          longer has to re-run validate at each step. */}
      {/* POLISH-SIGN-BANNER: the ambient "not cleanly signed — re-sign
          required" header banner jumps here (the pre-flight carries the full
          Part-11 signature status + re-sign action). */}
      <div id="signature-readiness" style={{ marginTop: 12, scrollMarginTop: 72 }}>
        <PreflightReport dossierId={dossierId} />
      </div>

      {tab === "files" && (
        <div className="viewer-files card glass">
          {filled.length === 0 ? (
            <div className="mut">No documents placed yet.</div>
          ) : (
            filled.map((n) => (
              <div key={n.heading} className="vf-folder">
                <div className="vf-head">
                  <b>{n.heading}</b> {n.title}{" "}
                  <span className="mut">{n.folder}</span>
                </div>
                {n.leaves.map((lf) => (
                  <div key={lf.leaf_id} className="vf-leaf">
                    <span aria-hidden>📄 </span>
                    {lf.title || lf.leaf_id}{" "}
                    <span className="mut">
                      {lf.href} · md5 {lf.checksum.slice(0, 8)}…
                    </span>
                  </div>
                ))}
              </div>
            ))
          )}
          <div className="mut" style={{ marginTop: 10, fontSize: 12 }}>
            {files?.live_leaf_count || 0} live leaves · placement{" "}
            {files?.placement_version}
          </div>
        </div>
      )}

      {tab === "outline" && (
        <div className="viewer-outline card glass">
          {!outline ? (
            <div className="mut">Loading outline…</div>
          ) : (
            <>
              <div className="mut">
                Sequence {outline.sequence} ·{" "}
                {outline.lifecycle_operations.length} lifecycle operations
              </div>
              <ul className="outline-ops">
                {outline.lifecycle_operations.map((op) => (
                  <li key={op.leaf_id}>
                    <code>{op.operation}</code> {op.leaf_id}
                  </li>
                ))}
              </ul>
              <details>
                <summary>eCTD backbone (index.xml)</summary>
                <pre className="xml">{outline.backbone["index.xml"]}</pre>
              </details>
            </>
          )}
        </div>
      )}
    </main>
  );
}
