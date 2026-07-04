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
  }, []);

  const activeStage = useMemo(() => {
    if (!view) return null;
    const stages = view.journey.stages;
    return (
      stages.find((s) => s.key === activeKey && !s.locked) ||
      stages.find((s) => s.current) ||
      stages[0]
    );
  }, [view, activeKey]);

  return (
    <>
      <TopNav subtitle="guided ANDS filing" extra={view && (
        <>
          <span className={`chip ${view.readiness.status === "READY" ? "ready" : "blocked"}`}>
            {view.readiness.status === "READY" ? "Ready to file" : `${view.readiness.percent}% ready`}
          </span>
          <button className="ghost" onClick={restart}>Start over</button>
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
            {/* R7: a labelling specialist looks for bilingual Module 1 / Product
                Monograph status. The journey session isn't a real dossier, so
                point them to the per-dossier panel where it actually lives. */}
            {activeStage?.key === "content" && (
              <div className="card glass" style={{ marginTop: 12, padding: 14 }}>
                <div className="mut" style={{ fontSize: 12, marginBottom: 6 }}>
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
      {/* R7: the guided journey is one product's path — a coordinator managing
          a portfolio enters here instead. Promoted from an afterthought link. */}
      <div className="hero-portfolio" style={{ marginTop: 18, display: "flex",
        gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
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
      <p className="sub" style={{ marginTop: 8 }}>
        Labelling / regulatory: bilingual Module 1 and Product Monograph (EN + FR)
        status live inside each dossier — open a dossier’s Module 1 to review it.
      </p>
      {error && <div className="notice bad">{error}</div>}
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
