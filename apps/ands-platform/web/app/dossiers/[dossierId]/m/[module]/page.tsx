"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useDossier } from "@/components/dossier/DossierContext";
import { SectionTree } from "@/components/dossier/SectionTree";
import { SectionPanel } from "@/components/dossier/SectionPanel";
import { ValidationCard } from "@/components/dossier/ValidationCard";
import { SequencePanel } from "@/components/dossier/SequencePanel";
import { CollabPane } from "@/components/dossier/CollabPane";
import { SubmissionTower } from "@/components/SubmissionTower";

export default function ModuleWorkspace() {
  const { content, loading, error } = useDossier();
  const params = useParams();
  const moduleId = String((params as any).module || "1");
  const [selected, setSelected] = useState("");

  const mod = content?.modules.find((m) => m.module === moduleId);

  useEffect(() => {
    setSelected("");
  }, [moduleId]);
  useEffect(() => {
    if (mod && !selected) {
      const first =
        mod.nodes.find(
          (n) =>
            n.kind === "document" &&
            n.applicability !== "suppressed" &&
            n.applicability !== "na"
        ) || mod.nodes[0];
      if (first) setSelected(first.section);
    }
  }, [mod, selected]);

  if (loading) return <div className="center mut">Loading dossier…</div>;
  if (error)
    return (
      <main className="stage">
        <div className="notice bad">{error}</div>
      </main>
    );
  if (!content || !mod)
    return (
      <main className="stage">
        <div className="notice">Module not found.</div>
      </main>
    );

  const node = mod.nodes.find((n) => n.section === selected) || null;

  return (
    <div className="workspace">
      <SectionTree module={mod} selected={selected} onSelect={setSelected} />
      <main className="ws-main">{node && <SectionPanel node={node} />}</main>
      <aside className="ws-aside">
        <SubmissionTower
          tiles={[]}
          status={content.gate.complete ? "READY" : "BLOCKED"}
          modules={content.tower}
        />
        <div className="card glass">
          <div className="mut" style={{ fontSize: 12 }}>
            Module {moduleId} — {mod.title.replace(/^Module \d+ — /, "")}
          </div>
          <div className="progress">
            <i style={{ width: `${mod.progress.percent}%` }} />
          </div>
          <div style={{ fontSize: 13 }}>
            {mod.progress.required_filled}/{mod.progress.required_total} required
            sections complete
          </div>
          {!content.gate.complete && content.gate.missing.length > 0 && (
            <div className="mut" style={{ fontSize: 12, marginTop: 8 }}>
              {content.gate.missing.length} item(s) still needed to file (documents,
              fee, or validation).
            </div>
          )}
          {(content.gate.unconfirmed_sample_count || 0) > 0 && (
            <div className="notice bad" style={{ fontSize: 12, marginTop: 8 }}>
              <b>⚠ {content.gate.unconfirmed_sample_count} sample/AI draft
              value(s) remain</b> — each must be reviewed and confirmed as your
              own content before this submission can be filed or exported.
            </div>
          )}
          <div className="ready-flags" style={{ marginTop: 8, fontSize: 12 }}>
            <span className={content.gate.section_complete ? "ok-flag" : "todo-flag"}>
              {content.gate.section_complete ? "✓" : "○"} Documents
            </span>{" · "}
            <span className={content.gate.fee_paid ? "ok-flag" : "todo-flag"}>
              {content.gate.fee_paid ? "✓" : "○"} Fee
            </span>{" · "}
            <span className={content.gate.validation_passed ? "ok-flag" : "todo-flag"}>
              {content.gate.validation_passed ? "✓" : "○"} Valid eCTD
            </span>
          </div>
        </div>
        <SequencePanel dossierId={content.dossier_id} />
        <ValidationCard dossierId={content.dossier_id} structural={content.validation} />
        <CollabPane dossierId={content.dossier_id} />
      </aside>
    </div>
  );
}
