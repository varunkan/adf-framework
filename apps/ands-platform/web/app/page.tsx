"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, session } from "@/lib/api";
import { UserChip } from "@/components/UserChip";
import type { JourneyView } from "@/lib/types";
import { StepRail } from "@/components/StepRail";
import { StepCard } from "@/components/StepCard";
import { ReadinessCard } from "@/components/ReadinessCard";
import { SubmissionTower } from "@/components/SubmissionTower";

export default function Page() {
  const [view, setView] = useState<JourneyView | null>(null);
  const [activeKey, setActiveKey] = useState<string>("orient");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [booting, setBooting] = useState(true);

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
      <header className="topbar">
        <span className="brand">
          <span className="dot" aria-hidden />
          ANDS&nbsp;Studio <small>· file a drug like a story</small>
        </span>
        <span className="spacer" />
        <UserChip />
        <Link className="chip" href="/dossiers">My dossiers</Link>
        <Link className="chip" href="/portfolio">Portfolio</Link>
        {view && (
          <>
            <span className={`chip ${view.readiness.status === "READY" ? "ready" : "blocked"}`}>
              {view.readiness.status === "READY" ? "Ready to file" : `${view.readiness.percent}% ready`}
            </span>
            <button className="ghost" onClick={restart}>
              Start over
            </button>
          </>
        )}
      </header>

      <div className="sr-only" aria-live="polite">
        {view && activeStage
          ? `Step: ${activeStage.label}. ${view.readiness.status === "READY" ? "Ready to file." : `${view.readiness.percent} percent ready.`}`
          : ""}
      </div>

      {!view ? (
        <Hero booting={booting} busy={busy} error={error} onStart={start} />
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
            />
            <ReadinessCard data={view.readiness} onResume={setActiveKey} />
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
}: {
  booting: boolean;
  busy: boolean;
  error: string;
  onStart: () => void;
}) {
  if (booting)
    return (
      <div className="center mut">Loading your filing…</div>
    );
  return (
    <div className="hero">
      <h1>
        File a drug with Health Canada,
        <br />
        <span className="accent-text">like telling a story.</span>
      </h1>
      <p>
        An Abbreviated New Drug Submission is one of the most complex things a
        company can file. This walks you through it step by step — explaining
        every term, branching you onto the right path, and showing your
        submission take shape in 3D until it&apos;s ready to send. No regulatory
        background needed.
      </p>
      <button className="start" onClick={onStart} disabled={busy}>
        {busy ? "Starting…" : "Start my submission →"}
      </button>
      <div style={{ marginTop: 14 }}>
        <Link className="chip" href="/dossiers">
          Or open your dossiers — every product in submission →
        </Link>
      </div>
      {error && <div className="notice bad">{error}</div>}
      <div className="sub">
        Grounded in real Health Canada process · your progress is saved
        automatically
      </div>
    </div>
  );
}
