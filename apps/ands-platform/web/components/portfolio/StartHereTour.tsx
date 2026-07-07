"use client";
// Round-9 (operations MAJOR, n=15): "maybe a short 'start here' guided path,
// because seeing all these pages, chips, and expanders at once is
// overwhelming." A dismissible AND re-launchable guided tour across
// Portfolio → Registry → Correspondence → Audit that walks through the scope
// card, the deadline card, the status chips and where daily tasks live.
// The launcher chip is always present, so — unlike the one-shot primer — the
// tour can be reopened any time. State persists per browser (localStorage).
import { useEffect, useState } from "react";
import Link from "next/link";

const STEPS = [
  {
    page: "portfolio",
    title: "1 · Portfolio — your daily start",
    href: "/portfolio",
    body:
      "Start each day here. The Client / sponsor scope card at the top picks " +
      "WHOSE records you're working on (nothing is pre-selected). Below it: " +
      "the 30-day deadline card (soonest first, overdue flagged) and one " +
      "status chip per dossier row — 'Ready to file' means every applicable " +
      "module has its required documents placed; 'Blocked' names the reason " +
      "inline. Your daily tasks live on the dossiers this page links to.",
  },
  {
    page: "registry",
    title: "2 · Registry — after approval",
    href: "/registry",
    body:
      "Once a product has its NOC, track it here: DIN and market status per " +
      "registration, the Right-to-Sell October-1 deadlines strip, and the " +
      "annual notification checklist (each tick is a controlled e-signature). " +
      "Everything is record-only — nothing transmits to Health Canada.",
  },
  {
    page: "correspondence",
    title: "3 · Correspondence — what HC sends you",
    href: "/correspondence",
    body:
      "Pick a dossier in scope, then: ingest notices (SDN/SAL/NOD/NON/NOC…) " +
      "in the Notice inbox — each shows what to do and the response window — " +
      "log letters in the hub, and watch live statutory clocks at the top. " +
      "Attach the actual HC notice document to each record.",
  },
  {
    page: "audit",
    title: "4 · Audit — prove it all happened",
    href: "/dossiers",
    body:
      "Open any dossier → Audit for its append-only Part-11 trail: every " +
      "change, sequence-numbered, actor- and workspace-stamped, exportable " +
      "as a hash-manifested CSV for inspections. The Validation & trust " +
      "panel there states how the guarantees are enforced.",
  },
] as const;

const KEY = "ands.opsTour"; // JSON: { open: boolean, step: number }

export function StartHereTour({ page }: {
  page: "portfolio" | "registry" | "correspondence" | "audit";
}) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const s = JSON.parse(raw);
        setOpen(Boolean(s.open));
        setStep(Math.min(Math.max(0, Number(s.step) || 0), STEPS.length - 1));
      }
    } catch { /* first visit — chip renders, tour closed */ }
  }, []);

  function persist(nextOpen: boolean, nextStep: number) {
    setOpen(nextOpen);
    setStep(nextStep);
    try {
      localStorage.setItem(KEY, JSON.stringify({ open: nextOpen, step: nextStep }));
    } catch { /* private mode — tour still works for this page view */ }
  }

  const s = STEPS[step];
  const onThisPage = s.page === page;

  return (
    <div style={{ margin: "10px 0" }}>
      {!open && (
        <button
          className="chip"
          onClick={() => persist(true, step)}
          title="A short guided path across Portfolio → Registry → Correspondence → Audit. Re-open it any time."
        >
          🧭 Start here — guided tour
        </button>
      )}
      {open && (
        <section className="card glass" aria-label="Start here guided tour"
          style={{ padding: "14px 18px", maxWidth: "84ch" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10,
            flexWrap: "wrap" }}>
            <b style={{ fontSize: 14 }}>{s.title}</b>
            <span className="mut" style={{ fontSize: 11 }}>
              step {step + 1} of {STEPS.length}
            </span>
            <span style={{ marginLeft: "auto" }} />
            <button className="ghost" style={{ fontSize: 11 }}
              onClick={() => persist(false, step)}
              title="Close the tour — the 🧭 chip stays here to re-open it any time">
              Close (re-open any time)
            </button>
          </div>
          <p className="mut" style={{ margin: "8px 0 10px", fontSize: 12.5,
            lineHeight: 1.55 }}>
            {s.body}
          </p>
          <div style={{ display: "flex", gap: 8, alignItems: "center",
            flexWrap: "wrap" }}>
            <button className="ghost" style={{ fontSize: 12 }}
              disabled={step === 0}
              onClick={() => persist(true, step - 1)}>
              ← Back
            </button>
            {step < STEPS.length - 1 ? (
              <button style={{ fontSize: 12 }}
                onClick={() => persist(true, step + 1)}>
                Next →
              </button>
            ) : (
              <button style={{ fontSize: 12 }}
                onClick={() => persist(false, 0)}>
                Done — start working
              </button>
            )}
            {!onThisPage && (
              <Link className="chip" href={s.href} style={{ fontSize: 11.5 }}>
                Open {s.page} page →
              </Link>
            )}
            {onThisPage && (
              <span className="chip ready" style={{ fontSize: 11 }}>
                you are on this page — look for the cards described above
              </span>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
