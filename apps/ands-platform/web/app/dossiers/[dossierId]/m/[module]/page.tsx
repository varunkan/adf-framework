"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useDossier } from "@/components/dossier/DossierContext";
import { SectionTree } from "@/components/dossier/SectionTree";
import { SectionPanel } from "@/components/dossier/SectionPanel";
import { ValidationCard } from "@/components/dossier/ValidationCard";
import { SequencePanel } from "@/components/dossier/SequencePanel";
import { LifecyclePanel } from "@/components/dossier/LifecyclePanel";
import { MonographPanel } from "@/components/dossier/MonographPanel";
import { CollabPane } from "@/components/dossier/CollabPane";
import { FirstRunWizard } from "@/components/dossier/FirstRunWizard";
import { CoveragePanel } from "@/components/dossier/CoveragePanel";
import { openPrintWindow, escapeHtml } from "@/components/dossier/printView";
import { SubmissionTower } from "@/components/SubmissionTower";
import { Disclosure } from "@/components/Disclosure";
import { dossierApi } from "@/lib/dossierApi";
import { LAST_VERIFIED } from "@/lib/regCitations";
import { CheckCircle2, Circle, AlertTriangle, BookOpen, Printer } from "lucide-react";

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
  const { content, loading, error, dossierId, index } = useDossier();
  const params = useParams();
  const moduleId = String((params as any).module || "1");
  const [selected, setSelected] = useState("");
  // Round-6 WS-A: when the Sequences panel holds an active export-block, force
  // its expander open so the blocking findings are never hidden.
  const [seqBlocked, setSeqBlocked] = useState(false);
  // P2-4: cross-module persistence for the secondary reference panels.
  const [seqOpen, setSeqOpen] = usePersistedFlag("ands.disc.sequences");
  const [lifeOpen, setLifeOpen] = usePersistedFlag("ands.disc.lifecycle");
  const [coverOpen, setCoverOpen] = usePersistedFlag("ands.disc.coverage");

  // Round-9 builder_forms MAJOR "No guided onboarding for first-time /
  // paper-native users" (n=6): the quick-start walkthrough auto-opens once per
  // browser and stays replayable from the rail's "Quick-start guide" chip.
  const [tourOpen, setTourOpen] = useState(false);
  useEffect(() => {
    try {
      if (!localStorage.getItem("ands.builder.quickstart.done")) setTourOpen(true);
    } catch {}
  }, []);
  const closeTour = () => {
    setTourOpen(false);
    try {
      localStorage.setItem("ands.builder.quickstart.done", "1");
    } catch {}
  };

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
      // Round-9 builder_forms MAJOR "No single authoritative 'what blocks
      // filing now'" (n=7): honour a ?sec= deep link from the gate card's
      // blocker list, else default to the first fileable document.
      let deep = "";
      try {
        deep = new URLSearchParams(window.location.search).get("sec") || "";
      } catch {}
      if (deep && mod.nodes.some((n) => n.section === deep)) {
        setSelected(deep);
        return;
      }
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
  const crit = content.validation?.criteria;

  // Round-9 builder_forms minor "No printable placed-vs-outstanding checklist"
  // (n=2): a ONE-CLICK binder-ready printout straight from the readiness rail —
  // per-module placed counts, every outstanding item (never truncated), the
  // triad, the ruleset stamp and the eValidator caveat verbatim.
  function printChecklist() {
    if (!content) return;
    const esc = escapeHtml;
    const mods = (content.tower || [])
      .map(
        (t) =>
          `<tr><td>M${esc(t.module)}</td><td>${t.required_filled}/${t.required_total}</td><td>${esc(t.state)}</td></tr>`
      )
      .join("");
    const outstanding = g.missing
      .map(
        (m) =>
          `<li>M${esc(String(m.module))} · ${esc(m.section)} — ${esc(m.title)}${
            m.needs_review ? " (needs review)" : ""
          }</li>`
      )
      .join("");
    const flag = (ok?: boolean) => (ok ? "✓" : "✗");
    openPrintWindow(
      `Placed vs outstanding — ${content.dossier_id}`,
      `<h1>Placed vs outstanding — ${esc(content.dossier_id)}</h1>
<div class="mut">Printed ${new Date().toISOString().slice(0, 10)}${
        crit
          ? ` · structural rules ${esc(crit.name)} v${esc(crit.version)}${
              crit.synced ? `, synced ${esc(crit.synced)}` : ""
            }`
          : ""
      } · guidance set verified ${esc(LAST_VERIFIED)}</div>
<h2>Ready-to-transmit gate</h2>
<ul>
<li>${flag(g.section_complete)} Documents — all required documents placed and confirmed</li>
<li>${flag(g.fee_paid)} Fee — the ANDS review fee is arranged</li>
<li>${flag(g.validation_passed)} Structural check — passed (structural / format completeness)</li>
${
  (g.unconfirmed_sample_count || 0) > 0
    ? `<li>✗ ${g.unconfirmed_sample_count} sample/AI draft value(s) not yet confirmed as your own content</li>`
    : ""
}
</ul>
<h2>Placed, per module</h2>
<table border="1" cellspacing="0" cellpadding="4" style="border-collapse:collapse;font-size:12px">
<tr><th>Module</th><th>Required placed</th><th>State</th></tr>${mods}</table>
<h2>Still outstanding (${g.missing.length})</h2>
${outstanding ? `<ul>${outstanding}</ul>` : "<p>Nothing outstanding — every required document is placed.</p>"}
<h2>Standing caveats</h2>
<ul>
<li>The structural check is not Health Canada's official eValidator — run eValidator before you transmit.</li>
<li>Placed/complete is a completeness signal, not validation or Health Canada acceptance.</li>
</ul>`
    );
  }

  // one blocker row inside the gate card's "What blocks filing now" list —
  // same-module blockers select in place; cross-module blockers deep-link.
  const blockerLink = (
    module: string,
    section: string,
    label: React.ReactNode
  ) =>
    module === moduleId ? (
      <button
        className="ghost"
        style={{ fontSize: 12, padding: "1px 6px", textAlign: "left" }}
        onClick={() => setSelected(section)}
      >
        {label}
      </button>
    ) : (
      <Link
        href={`/dossiers/${encodeURIComponent(content.dossier_id)}/m/${encodeURIComponent(
          module
        )}?sec=${encodeURIComponent(section)}`}
        style={{ fontSize: 12 }}
      >
        {label}
      </Link>
    );

  return (
    <>
      {/* Round-9 builder_forms BLOCKER "Target HC submission model / M1
          backbone version not visible or dated" (n=3) + BLOCKER "No per-client
          segregation indicator or per-client cost" (n=2): a slim PERSISTENT
          strip on the workspace header — the target spec versions, the dated
          rule provenance, and the active client with the isolation statement.
          (The per-section "HC guidance ↗" links are already stamped in
          SectionPanel.) */}
      <div
        className="mut"
        style={{
          maxWidth: 1360,
          margin: "0 auto",
          padding: "14px 24px 0",
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
          fontSize: 12,
        }}
      >
        <span
          className="chip"
          title="Every export is a genuine ICH eCTD 3.2.2 sequence with a CA Module 1 v2.2 regional backbone — inspect the real XML in the Application Viewer or the import-compatibility check."
        >
          Target: ICH eCTD 3.2.2 · CA Module 1 v2.2
        </span>
        {crit && (
          <span
            className="chip"
            title={`Structural rules modeled on ${crit.modeled_on}. Not Health Canada's official eValidator.`}
          >
            Rules: {crit.name} v{crit.version}
            {crit.synced ? ` · synced ${crit.synced}` : ""}
          </span>
        )}
        <span>guidance set verified {LAST_VERIFIED}</span>
        <span
          className="chip"
          style={{ marginLeft: "auto" }}
          title={
            "Documents and AI context are isolated per client: each sponsor lives in its own " +
            "workspace and cross-workspace reads are refused at the API layer. Honest limit: " +
            "per-client usage/cost reporting is not built yet — the Portfolio page's client " +
            "status export (CSV) is today's per-client artifact."
          }
        >
          Client: {index?.sponsor || index?.company_id || "this workspace"} ·
          isolated per client
        </span>
      </div>

      <div className="workspace">
        <SectionTree
          module={mod}
          selected={selected}
          onSelect={setSelected}
          opByLeaf={opByLeaf}
        />
        <main className="ws-main">
          {/* Round-9 builder_forms MAJOR "No guided onboarding" (n=6) — the
              dismissible, replayable first-run walkthrough. */}
          <FirstRunWizard open={tourOpen} onClose={closeTour} />
          {node && <SectionPanel node={node} op={node.leaf_id ? opByLeaf[node.leaf_id] : undefined} />}
          {/* Round-9 builder_forms BLOCKER "Bilingual/XML Product Monograph
              handling unclear and unenforced" (n=4): the Module-1 monograph
              panel is PROMOTED from a one-line right-rail expander to a
              first-class centre-panel section. */}
          {moduleId === "1" && (
            <div style={{ marginTop: 16 }}>
              <MonographPanel dossierId={content.dossier_id} />
            </div>
          )}
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
            {/* Round-9 builder_forms MAJOR "No single authoritative 'what
                blocks filing now' — redundant status signals" (n=7): the ONE
                itemized blocker list — every unresolved blocker with a jump
                link to its fix — lives here on the gate card, nowhere else.
                Blocking items are never truncated (the list scrolls). */}
            {!g.complete && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>
                  What blocks filing now
                </div>
                <ul
                  style={{
                    margin: "6px 0 0",
                    padding: 0,
                    listStyle: "none",
                    maxHeight: 190,
                    overflowY: "auto",
                    display: "grid",
                    gap: 3,
                  }}
                >
                  {g.missing.map((m) => (
                    <li key={`${m.module}-${m.section}`} style={{ fontSize: 12 }}>
                      {blockerLink(
                        String(m.module),
                        m.section,
                        <>
                          {m.section} — {m.title}
                          {m.needs_review ? " (needs review)" : ""} →
                        </>
                      )}
                    </li>
                  ))}
                  {!g.fee_paid && (
                    <li style={{ fontSize: 12 }}>
                      {blockerLink("1", "1.2.2", <>Fee not arranged — fee step 1.2.2 →</>)}
                    </li>
                  )}
                  {!g.validation_passed && (
                    <li style={{ fontSize: 12 }}>
                      <a href="#ws-validation" style={{ fontSize: 12 }}>
                        Structural check not passed — open the validation card →
                      </a>
                    </li>
                  )}
                </ul>
              </div>
            )}
            {/* Round-9 builder_forms MAJOR "eValidator caveat lives in
                tooltips — too missable" (n=2): the caveat is ALWAYS-VISIBLE
                text on the Ready-to-transmit card itself (kept verbatim); the
                tooltip above stays as reinforcement, not the only home. */}
            <div className="mut" style={{ fontSize: 11.5, marginTop: 10 }}>
              Structural check only — not Health Canada&apos;s official
              eValidator; run eValidator before you transmit.
            </div>
          </div>

          {/* Round-9 builder_forms MAJOR "No guided onboarding" (n=6) + minor
              "No printable placed-vs-outstanding checklist" (n=2): one-click
              rail actions — replay the walkthrough; print the binder copy. */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              className="chip"
              onClick={() => setTourOpen(true)}
              title="Reopen the step-by-step quick-start walkthrough"
            >
              <BookOpen size={13} aria-hidden style={{ marginRight: 4, verticalAlign: "-2px" }} />
              Quick-start guide
            </button>
            <button
              className="chip"
              onClick={printChecklist}
              title="Print a binder-ready placed-vs-outstanding checklist (PDF via your print dialog)"
            >
              <Printer size={13} aria-hidden style={{ marginRight: 4, verticalAlign: "-2px" }} />
              Print checklist (PDF)
            </button>
          </div>

          <div id="ws-validation">
            <ValidationCard dossierId={content.dossier_id} structural={content.validation} />
          </div>

          {/* Round-9 builder_forms MAJOR "PM-level rollup missing — …
              promote 'Collaboration & task assignments' out of the one-line
              expander at the bottom of the right column" (n=3): CollabPane is
              now a FIRST-CLASS rail card (assignees + blocked at a glance);
              its add-task form folds inside the pane to keep the card calm. */}
          <CollabPane dossierId={content.dossier_id} />

          {/* Round-6 WS-A (density reduction): the secondary reference panels —
              lifecycle, sequences/export — stay collapsed behind a one-line
              expander so the builder shows one primary thing per surface.
              Every panel stays reachable; none is removed. Open-state persists
              across module switches (P2-4). The 3D tower is likewise demoted
              here, below the gating triad above. */}
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
          {/* Round-9 builder_forms MAJOR "No pricing/coverage clarity vs
              consultant for solo filers" (n=2): the honest coverage & cost
              panel — no invented pricing, hedged consultant benchmark, real
              hand-off escape hatch. */}
          <Disclosure
            className="card glass"
            open={coverOpen}
            onOpenChange={setCoverOpen}
            summary={<span>Coverage &amp; cost — vs a consultant</span>}
          >
            <CoveragePanel dossierId={content.dossier_id} />
          </Disclosure>
        </aside>
      </div>
    </>
  );
}
