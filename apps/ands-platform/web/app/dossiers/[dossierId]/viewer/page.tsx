"use client";
import { useEffect, useState } from "react";
import { useDossier } from "@/components/dossier/DossierContext";
import { dossierApi } from "@/lib/dossierApi";
import type { OutlineView } from "@/lib/dossierTypes";

export default function ViewerPage() {
  const { content, loading, dossierId } = useDossier();
  const [tab, setTab] = useState<"files" | "outline">("files");
  const [outline, setOutline] = useState<OutlineView | null>(null);

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
        <a className="chip" href={`/api/dossier/ectd/${encodeURIComponent(dossierId)}/export/0000`}
          download title="Download the transmissible eCTD package (sequence 0000) — upload it via CESG WebTrader">
          ⬇ Export eCTD package
        </a>
      </div>
      <p className="mut" style={{ fontSize: 12 }}>
        The export is the spec folder tree (index.xml, ca-regional.xml, REP RT
        XML, every leaf at its href with checksums) zipped — what you upload
        through the CESG/FDA-ESG WebTrader.
      </p>

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
