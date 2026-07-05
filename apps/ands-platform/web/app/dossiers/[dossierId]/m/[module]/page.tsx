"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useDossier } from "@/components/dossier/DossierContext";
import { SectionTree } from "@/components/dossier/SectionTree";
import { SectionPanel } from "@/components/dossier/SectionPanel";
import { ValidationCard } from "@/components/dossier/ValidationCard";
import { SequencePanel } from "@/components/dossier/SequencePanel";
import { LifecyclePanel } from "@/components/dossier/LifecyclePanel";
import { MonographPanel } from "@/components/dossier/MonographPanel";
import { CollabPane } from "@/components/dossier/CollabPane";
import { SubmissionTower } from "@/components/SubmissionTower";
import { Disclosure } from "@/components/Disclosure";
import { dossierApi } from "@/lib/dossierApi";
import { CheckCircle2, Circle, AlertTriangle } from "lucide-react";

// Persist a Disclosure's open-state across module switches (P2-4): export is
// cross-module, so a filer working in "sequences & export" should not lose it
// on every M-tab click.
function usePersistedFlag(key: string, initial = false): [boolean, (v: boolean) => void] {
  const [v, setV] = useState(initial);
  useEffect(() => {
    try {
      const s = localStorage.getItem(key);
      if (s != null) setV(s === "1");
    } catch {}
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const set = (nv: boolean) => {
    setV(nv);
    try {
      localStorage.setItem(key, nv ? "1" : "0");
    } catch {}
  };
  return [v, set];
}

// A single triad flag — Documents / Fee / Structural-check — rendered in the
// SAME lucide-icon + Prism-token vocabulary the tree uses (P1-4), so one status
// language spans all three columns.
function GateFlag({
  ok,
  label,
  title,
}: {
  ok?: boolean;
  label: string;
  title?: string;
}) {
  const Icon = ok ? CheckCircle2 : Circle;
  return (
    <span className={`gate-flag ${ok ? "ok" : "todo"}`} title={title}>
      <Icon size={14} aria-hidden />
      {label}
    </span>
  );
}

export default function ModuleWorkspace() {
  const { content, loading, error, dossierId } = useDossier();
  const params = useParams();
  const moduleId = String((params as any).module || "1");
  const [selected, setSelected] = useState("");
  // Round-6 WS-A: when the Sequences panel holds an active export-block, force
  // its expander open so the blocking findings are never hidden.
  const [seqBlocked, setSeqBlocked] = useState(false);
  // P2-4: cross-module persistence for the secondary reference panels.
  const [seqOpen, setSeqOpen] = usePersistedFlag("ands.disc.sequences");
  const [lifeOpen, setLifeOpen] = usePersistedFlag("ands.disc.lifecycle");
  const [monoOpen, setMonoOpen] = usePersistedFlag("ands.disc.monograph");
  const [collabOpen, setCollabOpen] = usePersistedFlag("ands.disc.collab");

  // P1-2: the live/pending lifecycle operator per leaf, keyed by leaf_id, so
  // the tree can show NEW/REPL/APP/DEL honestly (0000 vs a 0001+ sequence).
  const [opByLeaf, setOpByLeaf] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!dossierId) return;
    let live = true;
    dossierApi
      .currentView(dossierId)
      .then((cv) => {
        if (!live) return;
        const map: Record<string, string> = {};
        for (const l of cv.live) map[l.leaf_id] = l.operation;
        setOpByLeaf(map);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [dossierId, content?.version]);

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
  const g = content.gate;

  return (
    <div className="workspace">
      <SectionTree
        module={mod}
        selected={selected}
        onSelect={setSelected}
        opByLeaf={opByLeaf}
      />
      <main className="ws-main">
        {node && <SectionPanel node={node} op={node.leaf_id ? opByLeaf[node.leaf_id] : undefined} />}
      </main>
      <aside className="ws-aside">
        {/* P1-4 — readiness-to-transmit as ONE concept in ONE vocabulary. The
            gating triad (Documents · Fee · Structural check) + the single
            blocker lead; the 3D tower is demoted below it. */}
        <div className="card glass gate-card">
          <div className="gate-head">
            <span className="mut" style={{ fontSize: 13, fontWeight: 600,
              letterSpacing: ".02em" }}>
              Ready to transmit
            </span>
            <span
              className={`ready-status ${g.complete ? "READY" : "BLOCKED"}`}
              style={{ marginLeft: "auto" }}
            >
              {g.complete ? "● READY" : "● BLOCKED"}
            </span>
          </div>
          {(g.unconfirmed_sample_count || 0) > 0 && (
            <div className="notice bad gate-notice" role="status">
              <AlertTriangle size={15} aria-hidden />
              <div>
                <b>
                  {g.unconfirmed_sample_count} sample/AI draft value(s) not yet
                  filable
                </b>{" "}
                — each must be reviewed and confirmed as your own content before
                this submission can be filed or exported.
              </div>
            </div>
          )}
          <div className="gate-flags" aria-live="polite">
            <GateFlag
              ok={g.section_complete}
              label="Documents"
              title="All required documents are placed and confirmed."
            />
            <GateFlag
              ok={g.fee_paid}
              label="Fee"
              title="The ANDS review fee is arranged."
            />
            <GateFlag
              ok={g.validation_passed}
              label="Structural check"
              title="Structural / format completeness check passed — NOT Health Canada's official eValidator. Run eValidator before you transmit."
            />
          </div>
          {!g.complete && g.missing.length > 0 && (
            <div className="mut" style={{ fontSize: 13, marginTop: 8 }}>
              {g.missing.length} item(s) still needed to file (documents, fee, or
              validation).
            </div>
          )}
        </div>

        <ValidationCard dossierId={content.dossier_id} structural={content.validation} />

        {/* Round-6 WS-A (density reduction): the secondary reference panels —
            lifecycle, sequences/export, monograph detail, collaboration — are
            each collapsed behind a one-line expander so the builder shows one
            primary thing per surface. Every panel stays reachable; none is
            removed. Open-state persists across module switches (P2-4). The 3D
            tower is likewise demoted here, below the gating triad above. */}
        <Disclosure
          className="card glass"
          summary={<span>Submission tower (3D module view)</span>}
        >
          <SubmissionTower
            tiles={[]}
            status={g.complete ? "READY" : "BLOCKED"}
            modules={content.tower}
            missing={g.missing}
          />
        </Disclosure>
        <Disclosure
          className="card glass"
          open={lifeOpen}
          onOpenChange={setLifeOpen}
          summary={<span>Submission lifecycle &amp; deficiency clock</span>}
        >
          <LifecyclePanel dossierId={content.dossier_id} />
        </Disclosure>
        <Disclosure
          className="card glass"
          open={seqOpen}
          onOpenChange={setSeqOpen}
          summary={
            <span>
              eCTD sequences &amp; package export
              {seqBlocked ? " — export blocked" : ""}
            </span>
          }
          forceOpen={seqBlocked}
          forceOpenNote="export blocked"
        >
          <SequencePanel
            dossierId={content.dossier_id}
            onBlockedChange={setSeqBlocked}
          />
        </Disclosure>
        {moduleId === "1" && (
          <Disclosure
            className="card glass"
            open={monoOpen}
            onOpenChange={setMonoOpen}
            summary={<span>Bilingual / XML Product Monograph detail</span>}
          >
            <MonographPanel dossierId={content.dossier_id} />
          </Disclosure>
        )}
        <Disclosure
          className="card glass"
          open={collabOpen}
          onOpenChange={setCollabOpen}
          summary={<span>Collaboration &amp; task assignments</span>}
        >
          <CollabPane dossierId={content.dossier_id} />
        </Disclosure>
      </aside>
    </div>
  );
}
