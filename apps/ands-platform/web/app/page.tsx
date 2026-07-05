"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { TopNav } from "@/components/TopNav";
import Link from "next/link";
import { api, session } from "@/lib/api";
import { dossierApi } from "@/lib/dossierApi";
import type { JourneyView } from "@/lib/types";
import { StepRail } from "@/components/StepRail";
import { StepCard } from "@/components/StepCard";
import { ReadinessCard } from "@/components/ReadinessCard";
import { SubmissionTower } from "@/components/SubmissionTower";
import { PrereqChecklist } from "@/components/PrereqChecklist";
import { TrustStrip } from "@/components/TrustStrip";
import { Modal } from "@/components/Modal";
import { ScrollText, History } from "lucide-react";

export default function Page() {
  const [view, setView] = useState<JourneyView | null>(null);
  const [activeKey, setActiveKey] = useState<string>("orient");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [booting, setBooting] = useState(true);
  // WS6: whether the external-prerequisites readiness screen has been dismissed
  // (persisted in PrereqChecklist). Loads from localStorage on mount; while
  // null we suppress the Hero so the checklist can show first.
  const [prereqAck, setPrereqAck] = useState<boolean | null>(null);
  useEffect(() => {
    try { setPrereqAck(window.localStorage.getItem("ands.prereqAck") === "1"); }
    catch { setPrereqAck(true); }
  }, []);

  // WS-JOURNEY (round-8 MAJOR, n=8): non-linear expert filers felt boxed in by
  // the hard linear gate. Expert mode makes later (locked) steps navigable as
  // "not-yet-recommended" instead of hard-locked. Persisted so an expert isn't
  // re-gated every visit; defaults OFF so juniors keep the guided path.
  const [expert, setExpert] = useState(false);
  useEffect(() => {
    try { setExpert(window.localStorage.getItem("ands.expertMode") === "1"); }
    catch { /* no storage — stay guided */ }
  }, []);
  const setExpertMode = useCallback((next: boolean) => {
    setExpert(next);
    try { window.localStorage.setItem("ands.expertMode", next ? "1" : "0"); }
    catch { /* non-fatal */ }
  }, []);

  // WS-JOURNEY (round-8 BLOCKER, n=4): "Start over" is now "Reset session"
  // behind a typed-confirmation modal with an explicit recoverable-from-version-
  // history note. This guards a Part-11-sensitive destructive-looking action.
  const [resetOpen, setResetOpen] = useState(false);
  const [resetConfirm, setResetConfirm] = useState("");

  // R7 portfolio-awareness: a coordinator is never trapped in one linear
  // journey — surface how many dossiers are in progress (and how many are
  // still blocked) so they can jump to the portfolio roll-up at any time.
  const [portfolio, setPortfolio] = useState<{ total: number; blocked: number }>(
    { total: 0, blocked: 0 });
  useEffect(() => {
    dossierApi.listDossiers()
      .then(({ dossiers }) => setPortfolio({
        total: dossiers.length,
        blocked: dossiers.filter((d) => !d.gate?.complete).length,
      }))
      .catch(() => { /* dossier service offline — link simply shows no count */ });
  }, []);

  // resume a saved session on load
  useEffect(() => {
    const id = session.load();
    if (!id) {
      setBooting(false);
      return;
    }
    api
      .get(id)
      .then((v) => {
        setView(v);
        setActiveKey(v.journey.position.current_key);
      })
      .catch(() => session.clear())
      .finally(() => setBooting(false));
  }, []);

  const start = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const v = await api.start({});
      session.save(v.id);
      setView(v);
      setActiveKey(v.journey.position.current_key);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const advance = useCallback(
    async (step: string, data?: Record<string, any>) => {
      setBusy(true);
      try {
        const v = await api.advance(view!.id, step, data ?? {});
        setView(v);
        setActiveKey(v.journey.position.current_key);
      } finally {
        setBusy(false);
      }
    },
    [view]
  );

  const restart = useCallback(() => {
    session.clear();
    setView(null);
    setActiveKey("orient");
    setResetOpen(false);
    setResetConfirm("");
  }, []);

  const activeStage = useMemo(() => {
    if (!view) return null;
    const stages = view.journey.stages;
    // In expert mode a locked step the user selected IS resolvable (they chose
    // to jump ahead). In guided mode we still refuse to open a locked step.
    return (
      stages.find((s) => s.key === activeKey && (expert || !s.locked)) ||
      stages.find((s) => s.current) ||
      stages[0]
    );
  }, [view, activeKey, expert]);

  return (
    <>
      <TopNav subtitle="guided ANDS filing" extra={view && (
        <>
          <span className={`chip ${view.readiness.status === "READY" ? "ready" : "blocked"}`}>
            {view.readiness.status === "READY" ? "Ready to file" : `${view.readiness.percent}% ready`}
          </span>
          <button className="ghost" onClick={() => { setResetConfirm(""); setResetOpen(true); }}>
            Reset session
          </button>
        </>
      )} />

      <div className="sr-only" aria-live="polite">
        {view && activeStage
          ? `Step: ${activeStage.label}. ${view.readiness.status === "READY" ? "Ready to file." : `${view.readiness.percent} percent ready.`}`
          : ""}
      </div>

      {!view ? (
        // WS6: gate Step 1 behind the external-prerequisites readiness screen.
        // Once acknowledged (persisted), the normal Hero shows.
        !booting && prereqAck === false ? (
          <PrereqChecklist onBegin={() => setPrereqAck(true)} />
        ) : (
          <Hero booting={booting} busy={busy} error={error} onStart={start}
            portfolio={portfolio} />
        )
      ) : (
        <div className="stage">
          <h1 className="sr-only">
            Guided Health Canada ANDS filing — {view.title}
          </h1>
          <StepRail
            stages={view.journey.stages}
            activeKey={activeStage?.key || ""}
            onSelect={setActiveKey}
            expert={expert}
            onExpertChange={setExpertMode}
          />
          <main className="main">
            {activeStage && (
              <StepCard
                stage={activeStage}
                view={view}
                onAdvance={advance}
                onView={setView}
                busy={busy}
              />
            )}
          </main>
          <aside className="spatial">
            <SubmissionTower
              tiles={view.readiness.tiles}
              status={view.readiness.status}
              modules={activeStage?.key === "content" ? view.content.tower : undefined}
              missing={activeStage?.key === "content" ? view.content.gate?.missing : undefined}
            />
            <ReadinessCard data={view.readiness} onResume={setActiveKey} />
            {/* WS-JOURNEY (round-8 BLOCKER, n=4): a persistent Audit-trail
                pointer. QA / Part-11 personas need to see WHERE the immutable
                who-changed-what-when record lives (and that it exports) without
                hunting. It points to the real per-dossier audit ledger — an
                append-only, actor-and-workspace-stamped Part-11 record with CSV
                export — not a new claim invented here. */}
            {view.journey.dossier_id && (
              <div className="card glass" style={{ marginTop: 12, padding: 14 }}>
                <div className="eyebrow" style={{ marginBottom: 8,
                  display: "flex", alignItems: "center", gap: 6 }}>
                  <ScrollText size={13} aria-hidden />
                  Audit trail
                </div>
                <p className="mut" style={{ fontSize: 12, margin: "0 0 8px" }}>
                  Every change to this dossier — document create/upload, AI-draft,
                  review, e-signature, validation, fees and transmission — is
                  written to an <b>append-only, tamper-evident Part-11 ledger</b>{" "}
                  stamped with who, what and when. Exportable as CSV for your
                  inspection binder.
                </p>
                <Link className="chip" href={`/dossiers/${encodeURIComponent(view.journey.dossier_id)}/audit`}>
                  Open the audit trail (immutable who/what/when) →
                </Link>
              </div>
            )}
            {/* R7: a labelling specialist looks for bilingual Module 1 / Product
                Monograph status. The journey session isn't a real dossier, so
                point them to the per-dossier panel where it actually lives. */}
            {activeStage?.key === "content" && (
              <div className="card glass" style={{ marginTop: 12, padding: 14 }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>
                  Labelling / Product Monograph
                </div>
                <p className="mut" style={{ fontSize: 12, margin: "0 0 8px" }}>
                  Bilingual Module 1 and the EN + FR Product Monograph (a
                  transmission blocker if either is missing) are tracked per
                  dossier.
                </p>
                <Link className="chip" href="/dossiers">
                  Open a dossier’s Module 1 →
                </Link>
              </div>
            )}
          </aside>
        </div>
      )}

      {/* WS-JOURNEY (round-8 BLOCKER, n=4): "Reset session" behind a typed
          confirmation. The panel personas (QA / Part-11) flagged a one-click
          "Start over" as a destructive-looking action with no guardrail. This
          requires typing RESET and states plainly what does and does NOT get
          discarded — the dossier record and its append-only audit trail live
          server-side and remain re-openable, so this is genuinely recoverable.
          Honest scope: it clears THIS local session pointer, not your data. */}
      {resetOpen && (
        <Modal
          title="Reset this session?"
          onClose={() => setResetOpen(false)}
          footer={
            <>
              <button className="ghost" onClick={() => setResetOpen(false)}>
                Keep working
              </button>
              <button
                disabled={resetConfirm.trim().toUpperCase() !== "RESET"}
                onClick={restart}
              >
                Reset session
              </button>
            </>
          }
        >
          <p style={{ marginTop: 0 }}>
            This clears the guided session on this device and returns you to the
            start. It does <b>not</b> delete your work.
          </p>
          <div className="notice" style={{ fontSize: 13, display: "flex", gap: 8, alignItems: "flex-start" }}>
            <History size={16} aria-hidden style={{ flexShrink: 0, marginTop: 1 }} />
            <div>
              <b>Recoverable from version history.</b> The dossier record and its
              append-only Part-11 audit trail are saved server-side under{" "}
              <b>{view?.journey.dossier_id || "your Dossier ID"}</b> and remain
              re-openable from the{" "}
              <Link className="chip" href="/dossiers" style={{ padding: "1px 8px" }}>dossier catalog</Link>.
              Resetting only detaches this local session — nothing is erased and
              no audit entry is removed.
            </div>
          </div>
          <label style={{ display: "block", marginTop: 14, fontSize: 13 }}>
            Type <b>RESET</b> to confirm
          </label>
          <input
            value={resetConfirm}
            onChange={(e) => setResetConfirm(e.target.value)}
            placeholder="RESET"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && resetConfirm.trim().toUpperCase() === "RESET") {
                restart();
              }
            }}
          />
        </Modal>
      )}
    </>
  );
}

function Hero({
  booting,
  busy,
  error,
  onStart,
  portfolio,
}: {
  booting: boolean;
  busy: boolean;
  error: string;
  onStart: () => void;
  portfolio: { total: number; blocked: number };
}) {
  if (booting)
    return (
      <div className="center mut">Loading your filing…</div>
    );
  return (
    <div className="hero">
      <h1>
        File your ANDS with Health Canada —
        <br />
        <span className="accent-text">guided end to end.</span>
      </h1>
      <p>
        An Abbreviated New Drug Submission is one of the most complex filings a
        company can make. This walks you through it step by step — every term
        explained in plain language with the regulatory vocabulary kept
        precise, the right pathway chosen for your product, and your
        submission&apos;s readiness visible at every moment until it&apos;s ready to
        send.
      </p>
      <button className="start" onClick={onStart} disabled={busy}>
        {busy ? "Starting…" : "Start my submission →"}
      </button>

      {error && <div className="notice bad">{error}</div>}

      {/* R7: the guided journey is one product's path — a coordinator managing
          a portfolio enters here instead. Promoted from an afterthought link.
          Grouped into a clearly-separated, labelled block so the two entry
          points and the labelling note read as one calm section, not a
          scattered row of links under the primary CTA. */}
      <section
        className="card glass"
        aria-label="Other ways to start"
        style={{
          marginTop: 26,
          padding: "16px 20px",
          textAlign: "left",
          maxWidth: 760,
          marginInline: "auto",
        }}
      >
        <div className="hero-portfolio" style={{ display: "flex", gap: 10,
          flexWrap: "wrap" }}>
          <Link className="chip" href="/dossiers"
            style={{ fontWeight: 700 }}>
            Managing several products? Open the dossier catalog
            {portfolio.total ? ` (${portfolio.total})` : ""} →
          </Link>
          <Link className="chip" href="/portfolio">
            Portfolio roll-up
            {portfolio.blocked ? ` · ${portfolio.blocked} in progress` : ""} →
          </Link>
        </div>
        <p className="mut" style={{ fontSize: 13, margin: "12px 0 0",
          lineHeight: 1.55 }}>
          Labelling / regulatory: bilingual Module 1 and Product Monograph
          (EN + FR) status live inside each dossier — open a dossier’s Module 1
          to review it.
        </p>
      </section>
      {/* WS-OVERALL (round-8) BLOCKER — replace the vague "progress saved
          automatically" footnote with a persistent, honest Trust & security
          strip answering the auditor's first questions (residency, tenant
          isolation, roles/SoD, audit-trail tamper controls) and stating
          SOC2/SSO plainly as roadmap. Progress auto-save is folded into the
          quieter line below so we don't lose that reassurance. */}
      <TrustStrip />
      <div className="sub" style={{ marginTop: 8 }}>
        Grounded in real Health Canada process · your progress is saved
        automatically
      </div>
    </div>
  );
}
