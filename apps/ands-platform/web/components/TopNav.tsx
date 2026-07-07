"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Compass, FolderTree, LayoutGrid, BadgeCheck, Mail, BookOpen,
  Languages, Map as MapIcon } from "lucide-react";
import { UserChip } from "./UserChip";
import { Modal } from "./Modal";
import { OnboardingSecuritySummary } from "./account/WorkspaceMfaPolicy";
import { dossierApi } from "@/lib/dossierApi";

// eCTD-native nav: a dossier IS the Module 1-5 tree (FolderTree); the registry
// tracks DIN / marketed status (BadgeCheck); correspondence is HC notices
// (Mail); Help is the regulatory reference (BookOpen).
//
// WS-ONBOARDING (round-8) #6 — one-line plain-English tooltips on every top-bar
// chip so a newcomer knows what each destination is without clicking.
const NAV = [
  { href: "/", label: "Journey", icon: Compass, exact: true,
    hint: "Your step-by-step path to a filing — start here if you're new." },
  { href: "/dossiers", label: "Dossiers", icon: FolderTree,
    hint: "Each product's eCTD Module 1–5 tree — build and edit submissions." },
  { href: "/portfolio", label: "Portfolio", icon: LayoutGrid,
    hint: "All your dossiers at a glance — progress, blockers and due dates." },
  { href: "/registry", label: "Registry", icon: BadgeCheck,
    hint: "Marketed products, DINs and Right-to-Sell status after approval." },
  { href: "/correspondence", label: "Correspondence", icon: Mail,
    hint: "Health Canada notices and letters tracked against each dossier." },
  { href: "/help", label: "Help", icon: BookOpen,
    hint: "Plain-language regulatory reference and the term glossary." },
];

const PRIMER_KEY = "ands.primerDismissed";
// R9-OVERALL "Start-screen density overwhelms low-tech users; nav orientation
// unclear" (n=4) — the tour remembers the picked role so the "where you'll
// live day to day" step stays personalized on re-launch.
const TOUR_ROLE_KEY = "ands.tourRole";

// ── R9-OVERALL "Bilingual EN/FR Module 1 / Product Monograph under-served —
//    footnote, not first-class" (n=4) ─────────────────────────────────────
// The panel asked for a Module 1 / PM readiness indicator ON the top-bar
// chips. This chip is fed by the real per-dossier bilingual-PM status
// (dossierApi.monographStatus, REQ-098): "PM n/m" = n of your m dossiers have
// the bilingual EN/FR Product Monograph complete at 1.3.1. Lazy + cached in
// sessionStorage (5 min) so the shared shell stays light; on any fetch
// failure (signed out, service down) the chip stays a plain labelled link —
// it never invents a number. The FR/EN parity view and landing-page preview
// halves of this finding live with the journey/dossier surfaces.
const PM_NAV_KEY = "ands.pmNavStatus.v1";
const PM_NAV_TTL_MS = 5 * 60_000;
const PM_NAV_SAMPLE = 8; // cap the per-dossier status calls; honest label below

function MonographNavChip() {
  const [counts, setCounts] =
    useState<{ done: number; total: number } | null>(null);
  useEffect(() => {
    let alive = true;
    try {
      const raw = sessionStorage.getItem(PM_NAV_KEY);
      if (raw) {
        const c = JSON.parse(raw) as { done: number; total: number; ts: number };
        if (Date.now() - c.ts < PM_NAV_TTL_MS) { setCounts(c); return; }
      }
    } catch { /* cache is best-effort */ }
    (async () => {
      try {
        const { dossiers } = await dossierApi.listDossiers();
        const sample = dossiers.slice(0, PM_NAV_SAMPLE);
        const rs = await Promise.allSettled(
          sample.map((d) => dossierApi.monographStatus(d.dossier_id)));
        const done = rs.filter(
          (r) => r.status === "fulfilled" && r.value.status === "complete"
        ).length;
        const c = { done, total: sample.length, ts: Date.now() };
        if (alive) setCounts(c);
        try { sessionStorage.setItem(PM_NAV_KEY, JSON.stringify(c)); }
        catch { /* non-fatal */ }
      } catch { /* signed out / unreachable — render without counts */ }
    })();
    return () => { alive = false; };
  }, []);
  const counted = counts !== null && counts.total > 0;
  return (
    <Link href="/dossiers" className="chip nav-chip"
      title={"Bilingual EN/FR Product Monograph readiness (Module 1.3.1) " +
        "across your dossiers — the labelling half of the work. " +
        (counted
          ? `${counts.done} of ${counts.total} dossiers bilingual-complete` +
            (counts.total === PM_NAV_SAMPLE
              ? ` (first ${PM_NAV_SAMPLE} dossiers)` : "") + "."
          : "Open a dossier's Module 1 to review it.")}
      aria-label={"Module 1 Product Monograph readiness" +
        (counted ? `: ${counts.done} of ${counts.total} complete` : "")}>
      <Languages size={14} aria-hidden /> M1 · PM
      {counted ? ` ${counts.done}/${counts.total}` : ""}
    </Link>
  );
}

// ── R9-OVERALL "Start-screen density overwhelms low-tech users; nav
//    orientation unclear" (n=4) — the guided first-run walkthrough + the
//    role-based "where you'll live day to day" orientation the static primer
//    lacked. Re-launchable from the persistent "Tour" button in the topbar
//    (the round-8 primer was a one-shot banner). ────────────────────────────
type TourRole = "inhouse" | "cro" | "pm" | "qa";

const TOUR_ROLES: { id: TourRole; label: string; home: string;
  homeLabel: string; why: string }[] = [
  { id: "inhouse", label: "In-house RA — filing for my own company",
    home: "/", homeLabel: "Journey",
    why: "Journey walks the whole filing step by step, and Dossiers is " +
      "where your Module 1–5 documents live. You'll spend your day between " +
      "those two; Portfolio is your at-a-glance status check." },
  { id: "cro", label: "CRO / consultant — filing for client companies",
    home: "/portfolio", homeLabel: "Portfolio",
    why: "Portfolio is the multi-client view: pick the sponsor scope first " +
      "(the switcher at the top), then work each client's dossiers. " +
      "Correspondence keeps every HC notice tied to the right client." },
  { id: "pm", label: "Project manager — I track status, dates and blockers",
    home: "/portfolio", homeLabel: "Portfolio",
    why: "Portfolio carries the deadline strip, per-dossier owners, the " +
      "who-is-blocked-on-what roll-up and the exportable client status " +
      "report — your day-to-day lives there." },
  { id: "qa", label: "QA / auditor — I verify controls and records",
    home: "/account", homeLabel: "Account & security",
    why: "Account & security holds the role/segregation-of-duties table, " +
      "MFA and session policy, and the append-only audit exports. Help " +
      "carries the rule catalogue and how the ruleset stays synced." },
];

function NavTour({ onClose, onShowPrimer }:
  { onClose: () => void; onShowPrimer: () => void }) {
  const [role, setRole] = useState<TourRole | null>(() => {
    try {
      const r = localStorage.getItem(TOUR_ROLE_KEY);
      return TOUR_ROLES.some((x) => x.id === r) ? (r as TourRole) : null;
    } catch { return null; }
  });
  // step 0 = role pick · 1 = your home base · 2 = the map · 3 = journey scope
  // · 4 = who stays accountable
  const [step, setStep] = useState(0);
  const picked = TOUR_ROLES.find((r) => r.id === role) || null;
  function pick(r: TourRole) {
    setRole(r);
    try { localStorage.setItem(TOUR_ROLE_KEY, r); } catch { /* non-fatal */ }
    setStep(1);
  }
  const last = 4;
  return (
    <Modal title={`60-second tour · step ${step + 1} of ${last + 1}`}
      onClose={onClose}
      footer={
        <>
          {step > 0 && (
            <button className="ghost" onClick={() => setStep(step - 1)}>
              ← Back
            </button>
          )}
          {step > 0 && step < last && (
            <button onClick={() => setStep(step + 1)}>Next →</button>
          )}
          {step === last && <button onClick={onClose}>Done</button>}
        </>
      }>
      <div style={{ display: "grid", gap: 10, fontSize: 13.5,
        lineHeight: 1.55 }}>
        {step === 0 && (
          <>
            <p style={{ margin: 0 }}>
              <b>Which is closest to you?</b> This only tailors where the tour
              points first — every area stays available to everyone.
            </p>
            {TOUR_ROLES.map((r) => (
              <button key={r.id} className={role === r.id ? "" : "ghost"}
                style={{ textAlign: "left" }} onClick={() => pick(r.id)}>
                {r.label}
              </button>
            ))}
          </>
        )}
        {step === 1 && (
          <>
            <p style={{ margin: 0 }}>
              <b>Where you&apos;ll live day to day:{" "}
                {picked ? picked.homeLabel : "Journey"}.</b>
            </p>
            <p className="mut" style={{ margin: 0 }}>
              {picked ? picked.why
                : "Journey walks the whole filing step by step — the safest " +
                  "place to start."}
            </p>
            <p style={{ margin: 0 }}>
              <Link href={picked ? picked.home : "/"} onClick={onClose}>
                Open {picked ? picked.homeLabel : "Journey"} →
              </Link>
            </p>
          </>
        )}
        {step === 2 && (
          <>
            <p style={{ margin: 0 }}><b>The map — all six areas:</b></p>
            <ul style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 5 }}>
              {NAV.map(({ label, hint }) => (
                <li key={label}><b>{label}</b> — {hint}</li>
              ))}
            </ul>
            <p className="mut" style={{ margin: 0 }}>
              The <b>M1 · PM</b> chip beside them tracks the bilingual EN/FR
              Product Monograph — the labelling half of a generic filing.
            </p>
          </>
        )}
        {step === 3 && (
          <>
            <p style={{ margin: 0 }}>
              <b>The whole journey, end to end.</b> Eleven steps from
              &quot;get oriented&quot; to &quot;track &amp; respond&quot; —
              your preparation is the long pole (weeks to months); Health
              Canada&apos;s screening and review clocks are the statutory part.
            </p>
            <p style={{ margin: 0 }}>
              <Link href="/help#journey-at-a-glance" onClick={onClose}>
                See every phase with rough time estimates →
              </Link>
            </p>
          </>
        )}
        {step === 4 && (
          <>
            {/* R9-OVERALL "No explicit human-oversight/accountability
                statement" (n=3) — stated at orientation, not only on Help. */}
            <p style={{ margin: 0 }}><b>Who stays accountable — you.</b></p>
            <p className="mut" style={{ margin: 0 }}>
              This tool is an aid, not a substitute for a human regulatory
              reviewer. Nothing is final until a named person reviews and
              e-signs, and responsibility for anything an AI-labelled draft
              got wrong that survives review rests with that signing reviewer.
              And remember the yellow banner: this demo environment transmits
              nothing to Health Canada.
            </p>
            <p style={{ margin: 0 }}>
              <button className="ghost" style={{ fontSize: 12 }}
                onClick={() => { onShowPrimer(); onClose(); }}>
                Show the welcome primer again
              </button>
            </p>
          </>
        )}
      </div>
    </Modal>
  );
}

// #6 — a post-login "What you'll do here" primer + a "New to ANDS? Start here"
// pointer, dismissible and persisted. Rendered once at the top of every
// authenticated page (TopNav is the single shared shell). #5 — surfaces the
// session/MFA security posture up front rather than buried in settings.
// R9-OVERALL "Start-screen density overwhelms" (n=4): now re-launchable (the
// topbar Tour button re-opens it via forceOpen) and it offers the guided tour.
function OnboardingPrimer({ forceOpen, onStartTour, onForcedClose }:
  { forceOpen: boolean; onStartTour: () => void; onForcedClose: () => void }) {
  const [dismissed, setDismissed] = useState<boolean | null>(null);
  useEffect(() => {
    try { setDismissed(localStorage.getItem(PRIMER_KEY) === "1"); }
    catch { setDismissed(true); }
  }, []);
  if (!forceOpen && dismissed !== false) return null;
  function close() {
    setDismissed(true);
    onForcedClose(); // a re-shown primer must be dismissible again
    try { localStorage.setItem(PRIMER_KEY, "1"); } catch { /* non-fatal */ }
  }
  return (
    <div className="notice" style={{ margin: "10px auto 0", maxWidth: 1100,
      fontSize: 13, display: "grid", gap: 6 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "baseline",
        flexWrap: "wrap" }}>
        <b>What you&apos;ll do here</b>
        <span className="chip ready" style={{ fontSize: 11 }}>
          New to ANDS? Start here
        </span>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button className="ghost" style={{ fontSize: 12 }} onClick={onStartTour}>
          Take the 60-second tour
        </button>
        <button className="ghost" style={{ fontSize: 12 }} onClick={close}>
          Got it
        </button>
      </div>
      <div className="mut">
        ANDS Studio helps you assemble a Health Canada eCTD submission and get it
        ready to transmit. The usual path: <b>Journey</b> walks you step by step,
        <b> Dossiers</b> is where you build each product&apos;s Module 1–5 tree, and
        <b> Portfolio</b> shows everything&apos;s status at a glance.{" "}
        <Link href="/">Open the guided Journey →</Link>
        {/* R9-OVERALL "Pricing and cost model invisible" (n=6): pricing is
            published and one click from the overview, where this primer
            renders. */}{" "}
        · <Link href="/help#pricing">Pricing &amp; cost model</Link>
        {" · "}
        <Link href="/help#journey-at-a-glance">
          The whole journey, with time estimates
        </Link>
      </div>
      {/* R9-OVERALL "No explicit human-oversight/accountability statement —
          over-trust risk for newcomers" (n=3): the oversight sentence sits in
          the orientation primer (shown on the overview and every page, and
          re-launchable from the Tour button) — not only buried in Help. */}
      <div className="mut">
        <b>A human stays accountable:</b> this tool is an aid, not a substitute
        for a regulatory reviewer — nothing is final until a named person
        reviews and e-signs, and responsibility for anything an AI-labelled
        draft got wrong that survives review rests with that signing reviewer.
      </div>
      <OnboardingSecuritySummary />
    </div>
  );
}

// #6 — a persistent, honest demo-vs-production banner. This evaluation build
// does not transmit to Health Canada and does not send email; make that plain
// on every page so nobody mistakes it for a live production tenant.
function DemoBanner() {
  return (
    <div style={{ background: "rgba(255,209,102,.14)",
      borderBottom: "1px solid rgba(255,209,102,.35)", fontSize: 12,
      textAlign: "center", padding: "5px 12px", color: "#ffe3a3" }}>
      <b>Demo / evaluation environment</b> — nothing here is transmitted to
      Health Canada and no email is sent. Use it to explore the full workflow
      safely.
    </div>
  );
}

// Shared, iconified top nav used on every authenticated page — single source of
// truth (was duplicated + inconsistent per page). Highlights the active route.
export function TopNav({ subtitle, extra }: { subtitle?: string; extra?: React.ReactNode }) {
  const path = usePathname() || "/";
  // R9-OVERALL "Start-screen density overwhelms; nav orientation unclear"
  // (n=4): tour + re-shown-primer state lives here so the "Tour" chip can
  // re-launch either from any page.
  const [tourOpen, setTourOpen] = useState(false);
  const [primerForced, setPrimerForced] = useState(false);
  return (
    <>
      <DemoBanner />
      <header className="topbar">
        <Link href="/" className="brand" style={{ textDecoration: "none", color: "inherit" }}>
          <span className="dot" aria-hidden />
          ANDS&nbsp;Studio{subtitle ? <small>· {subtitle}</small> : null}
        </Link>
        <nav className="topnav" aria-label="Primary">
          {NAV.map(({ href, label, icon: Icon, exact, hint }) => {
            const active = exact ? path === href : path === href || path.startsWith(href + "/");
            return (
              <Link key={href} href={href}
                title={hint}
                className={`chip nav-chip${active ? " nav-chip-active" : ""}`}
                aria-current={active ? "page" : undefined}>
                <Icon size={14} aria-hidden /> {label}
              </Link>
            );
          })}
          {/* R9-OVERALL bilingual M1/PM first-class (n=4): live readiness chip */}
          <MonographNavChip />
        </nav>
        <span className="spacer" />
        {/* R9-OVERALL (n=4): the primer/tour are re-launchable, not one-shot */}
        <button className="ghost" style={{ fontSize: 12, display: "inline-flex",
          alignItems: "center", gap: 4 }}
          title="Re-run the 60-second orientation tour or re-open the welcome primer — any time, from any page."
          onClick={() => setTourOpen(true)}>
          <MapIcon size={14} aria-hidden /> Tour
        </button>
        {extra}
        <UserChip />
      </header>
      <OnboardingPrimer forceOpen={primerForced}
        onStartTour={() => setTourOpen(true)}
        onForcedClose={() => setPrimerForced(false)} />
      {tourOpen && (
        <NavTour onClose={() => setTourOpen(false)}
          onShowPrimer={() => setPrimerForced(true)} />
      )}
    </>
  );
}
