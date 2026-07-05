"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Compass, FolderTree, LayoutGrid, BadgeCheck, Mail, BookOpen } from "lucide-react";
import { UserChip } from "./UserChip";
import { OnboardingSecuritySummary } from "./account/WorkspaceMfaPolicy";

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

// #6 — a post-login "What you'll do here" primer + a "New to ANDS? Start here"
// pointer, dismissible and persisted. Rendered once at the top of every
// authenticated page (TopNav is the single shared shell). #5 — surfaces the
// session/MFA security posture up front rather than buried in settings.
function OnboardingPrimer() {
  const [dismissed, setDismissed] = useState<boolean | null>(null);
  useEffect(() => {
    try { setDismissed(localStorage.getItem(PRIMER_KEY) === "1"); }
    catch { setDismissed(true); }
  }, []);
  if (dismissed !== false) return null;
  function close() {
    setDismissed(true);
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
        </nav>
        <span className="spacer" />
        {extra}
        <UserChip />
      </header>
      <OnboardingPrimer />
    </>
  );
}
