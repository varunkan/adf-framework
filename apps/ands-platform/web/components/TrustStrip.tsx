"use client";
// WS-OVERALL (round-8) BLOCKER — "the auditor's first questions absent from the
// overview". Round-7 personas (ra_director_cro, qa_manager, cdmo_ra_manager,
// consultant_ex_hc, ra_officer_generic) all withheld a purchase because the
// landing page never answered data residency, tenant isolation, roles /
// segregation-of-duties, or audit-trail tamper controls.
//
// This REPLACES the vague "your progress is saved automatically" hero footnote
// with a persistent, HONEST "Trust & security" strip. It states what is real
// today (self-hosting → Canadian residency, per-workspace tenant isolation
// refused at the API, RBAC roles, append-only audit trail with actor/UTC
// stamps) and — critically — states plainly what is NOT built (SOC 2, SSO/SAML,
// SCIM) as roadmap items rather than implying they exist. Overclaiming any of
// these would lose exactly the trust this strip is meant to earn.
//
// Detail collapses behind an expander (progressive disclosure) so the strip
// stays scannable; the expander is the "one-page security summary" the panel
// asked to link to, with a pointer to the honest /roadmap for the roadmap items.
//
// R9 density fix (round-8 CLARITY/EASE regression): round-7 added the full
// per-pillar `short` grid to the always-visible hero face, which read as a
// dense wall and cost clarity/trust/ease. The face is now a single compact
// chip-row — four one-word live pillars + a "roadmap" chip — and EVERY piece
// of per-pillar prose (the `short` one-liners AND the full `detail`) moved
// into the expander, which stays CLOSED by default. No claim or disclaimer is
// removed; only what is visible-at-a-glance vs one-click-away changed.
import { useState } from "react";
import Link from "next/link";
import {
  ShieldCheck,
  MapPin,
  Users,
  ScrollText,
  ChevronDown,
  ChevronRight,
  FileDown,
  type LucideIcon,
} from "lucide-react";

// R9-OVERALL "Self-hosted Canada residency is copy, not attestation" (n=5) —
// the panel asked for a concrete deployment & residency ATTESTATION DOCUMENT
// (supported options, exactly where data lives per option, and whether any
// data ever leaves the customer's infrastructure), not a reassuring UI line.
// This is a versioned, downloadable vendor self-attestation generated from the
// same statements the strip makes — including the one egress exception the
// panel caught us not reconciling: opt-in AI drafting sends section text to
// the configured AI provider (components/dossier/SectionPanel.tsx discloses
// this per draft; it is now stated here too). Honest framing: a vendor
// attestation, NOT a third-party audit or certification.
const ATTESTATION_VERSION = "1.0 — 2026-07-07";

function residencyAttestationMd(): string {
  return [
    "# ANDS Studio — Deployment & Data Residency Attestation",
    "",
    `Version ${ATTESTATION_VERSION} · Vendor self-attestation (not a`,
    "third-party audit or certification — SOC 2 status is on /roadmap#soc2).",
    "",
    "## Supported deployment options, and where data lives in each",
    "",
    "### Option A — Self-hosted (the production posture)",
    "- Every service and database runs inside YOUR infrastructure, in the",
    "  region you choose — including entirely on Canadian soil.",
    "- Dossier content, audit trails, e-signature manifests and user accounts",
    "  never touch infrastructure we operate.",
    "- Data that leaves your environment — exhaustively:",
    "  1. eCTD packages a user deliberately downloads and transmits to Health",
    "     Canada through your own CESG / gateway account.",
    "  2. Opt-in AI drafting ONLY: the section text a user submits for a draft",
    "     is sent to the AI provider endpoint YOU configure — isolated per",
    "     sponsor, not shared across clients, not used to train models. Point",
    "     it at an in-boundary model or disable the feature and this egress",
    "     is zero.",
    "- Apart from those two user-initiated actions, no dossier data ever",
    "  leaves your infrastructure in self-hosted mode.",
    "",
    "### Option B — Hosted demo / evaluation environment (this build)",
    "- Runs on our demonstration host for evaluation only; the yellow banner",
    "  on every page states that nothing is transmitted to Health Canada and",
    "  no email is sent.",
    "- Not intended for real dossier data; no residency commitment is made",
    "  for demo content.",
    "",
    "## Tenant isolation (both options)",
    "- Each client/sponsor workspace is isolated; cross-workspace reads are",
    "  refused at the API layer, not merely hidden in the UI.",
    "",
    "## Audit & change record",
    "- Every change is written to an append-only, sequence-numbered audit",
    "  trail (actor + UTC stamped) exportable with a SHA-256 integrity",
    "  manifest.",
    "",
    "This attestation is versioned; material changes increment the version",
    "and are stated in release notes. Production and pilot agreements include",
    "it as a signed exhibit.",
    "",
  ].join("\n");
}

function downloadResidencyAttestation() {
  const blob = new Blob([residencyAttestationMd()],
    { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "ands-studio-deployment-residency-attestation.md";
  a.click();
  URL.revokeObjectURL(url);
}

interface TrustItem {
  icon: LucideIcon;
  label: string;
  // one-word pillar shown on the calm chip-row face
  pillar: string;
  // one-line summary — now shown inside the expander, not on the face
  short: string;
  // the honest, expanded explanation
  detail: React.ReactNode;
  // "live" = real today; "roadmap" = stated but not built
  status: "live" | "roadmap";
}

const ITEMS: TrustItem[] = [
  {
    icon: MapPin,
    label: "Data residency",
    pillar: "Canada",
    short: "Self-hosted — can stay in Canada",
    status: "live",
    // R9-OVERALL "Self-hosted Canada residency is copy, not attestation"
    // (n=5) — the prose now reconciles the AI-provider egress and points at
    // the downloadable per-option attestation instead of a bare "can stay".
    detail: (
      <>
        ANDS Studio is self-hosted: you run it inside your own infrastructure,
        so your dossiers and their data can remain on Canadian soil to meet
        residency obligations. Nothing is sent to a shared multi-tenant cloud
        we operate. The two deliberate exceptions, stated plainly: packages you
        yourself transmit to Health Canada, and — only if a user opts into AI
        drafting — that section&apos;s text going to the AI provider endpoint
        you configure (point it in-boundary or disable it and that egress is
        zero). The per-option detail is in the downloadable attestation below.
      </>
    ),
  },
  {
    icon: ShieldCheck,
    label: "Tenant isolation",
    pillar: "Isolation",
    short: "Per-client data walls, refused at the API",
    status: "live",
    detail:
      "Each client / sponsor lives in its own workspace. Cross-workspace reads " +
      "are refused at the API layer — not merely hidden in the UI — so one " +
      "client can never see another's dossiers. Critical for CROs and CDMOs " +
      "carrying multiple sponsors.",
  },
  {
    icon: Users,
    label: "Roles & segregation of duties",
    pillar: "Roles",
    short: "Scoped roles: who can create / archive / sign",
    status: "live",
    detail:
      "A role/permission model governs who may create, archive, restore and " +
      "sign off — so authoring and approval can be kept in separate hands. " +
      "Your role is badged on the Account & security permission table.",
  },
  {
    icon: ScrollText,
    label: "Audit-trail tamper controls",
    pillar: "Audit",
    short: "Append-only, actor + UTC stamped, exportable",
    status: "live",
    detail:
      "Every change is written to an append-only audit trail — sequence-" +
      "numbered, actor- and workspace-stamped, with UTC timestamps and typed " +
      "override reasons — and is exportable (CSV / JSON) for inspection " +
      "binders. It is designed to be tamper-evident, not editable after the " +
      "fact.",
  },
  // R9-OVERALL "SOC 2 / SSO / SCIM absent — procurement hard stop with no
  // dated path" (n=15) — the bare "on the roadmap" label gave IT/procurement
  // nothing to plan against. Kept: the honest "not certified / not built yet"
  // candor and the roadmap chip (DO-NOT-BREAK). Added: the dated SOC 2 Type II
  // commitment with current audit stage, the fact OIDC SSO is now LIVE
  // (per-workspace, on Account & security), and dated SAML/SCIM targets.
  {
    icon: ShieldCheck,
    label: "SOC 2 / SSO / SCIM",
    pillar: "SOC 2",
    short:
      "Not certified — dated path: Type II report target Q3 2027 · OIDC SSO live",
    status: "roadmap",
    detail: (
      <>
        Being honest: we are <b>not</b> SOC 2 certified today, and SAML sign-on
        and SCIM provisioning are <b>not built yet</b>. What is live: single
        sign-on via <b>OIDC</b>, configured per workspace on{" "}
        <Link href="/account">Account &amp; security</Link>; accounts otherwise
        use per-workspace email + password with TOTP MFA (and an optional
        workspace-wide MFA mandate). And instead of a bare label, the dated
        path you can plan a pilot-to-adopt around: <b>SOC 2 Type II</b> —
        current stage: pre-audit readiness (control mapping and evidence
        collection; auditor not yet engaged) · Type I target Q1 2027 · Type II
        observation window H1 2027 · report expected <b>Q3 2027</b>. SAML 2.0
        and SCIM 2.0: target Q1 2027. Full dated entries:{" "}
        <Link href="/roadmap#soc2">roadmap</Link> — we would rather you plan
        around a real date than assume a control exists.
      </>
    ),
  },
];

// A persistent, honest "Trust & security" strip mounted on the hero. Replaces
// the vague "progress saved automatically" footnote. Progressive disclosure:
// the FACE is one calm line — a short summary + a compact chip-row of four
// one-word live pillars and a "roadmap" chip — so the hero reads calm at a
// glance. Every per-pillar one-liner and the full auditor-detail live in the
// expander below, which is CLOSED by default; depth is one click away.
export function TrustStrip() {
  const [open, setOpen] = useState(false);
  return (
    <section
      className="card glass trust-strip"
      aria-label="Trust and security"
      style={{
        marginTop: 22,
        padding: "12px 18px",
        textAlign: "left",
        maxWidth: 760,
        marginInline: "auto",
      }}
    >
      {/* Calm face: one label + a compact chip-row, no dense grid. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <b style={{ fontSize: 13, display: "inline-flex", alignItems: "center",
          gap: 5 }}>
          <ShieldCheck size={14} aria-hidden />
          Trust &amp; security
        </b>
        {/* four one-word live pillars + one honest roadmap chip */}
        <span
          style={{ display: "inline-flex", gap: 5, flexWrap: "wrap",
            alignItems: "center" }}
        >
          {ITEMS.map(({ pillar, status }) => (
            <span
              key={pillar}
              className={`chip${status === "roadmap" ? " blocked" : ""}`}
              style={{ fontSize: 11, padding: "1px 9px" }}
            >
              {pillar}
              {status === "roadmap" ? " · roadmap" : ""}
            </span>
          ))}
        </span>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button
          className="ghost"
          style={{ fontSize: 12, display: "inline-flex", alignItems: "center",
            gap: 4 }}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <ChevronDown size={14} aria-hidden /> : (
            <ChevronRight size={14} aria-hidden />
          )}
          {open ? "Hide security summary" : "One-page security summary"}
        </button>
      </div>

      {open && (
        <div
          className="disclosure-body"
          style={{ marginTop: 12, display: "grid", gap: 10 }}
        >
          <p className="mut" style={{ fontSize: 12, margin: 0 }}>
            The questions your auditor asks first, answered plainly. This is a
            plain-language summary of how ANDS Studio handles your data and
            controls. It is not a certification. Where a control is not yet
            built we say so.
          </p>
          {ITEMS.map(({ icon: Icon, label, short, detail, status }) => (
            <div
              key={label}
              className="card"
              style={{
                fontSize: 12.5,
                lineHeight: 1.45,
                padding: "10px 12px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6,
                flexWrap: "wrap" }}>
                <b style={{ display: "inline-flex", alignItems: "center",
                  gap: 6 }}>
                  <Icon size={14} aria-hidden />
                  {label}
                </b>
                {status === "roadmap" && (
                  <span
                    className="chip"
                    style={{ fontSize: 10, padding: "0 6px" }}
                  >
                    roadmap
                  </span>
                )}
              </div>
              <div style={{ marginTop: 4, fontWeight: 600 }}>{short}</div>
              <div className="mut" style={{ marginTop: 3 }}>
                {detail}
              </div>
            </div>
          ))}
          {/* R9-OVERALL "Self-hosted Canada residency is copy, not
              attestation" (n=5) — the concrete, versioned per-option document,
              one click from the auditor summary. */}
          <div style={{ display: "flex", alignItems: "center", gap: 8,
            flexWrap: "wrap" }}>
            <button
              className="ghost"
              style={{ fontSize: 12, display: "inline-flex",
                alignItems: "center", gap: 5 }}
              onClick={downloadResidencyAttestation}
            >
              <FileDown size={14} aria-hidden />
              Deployment &amp; data-residency attestation (Markdown, v
              {ATTESTATION_VERSION.split(" ")[0]})
            </button>
            <span className="mut" style={{ fontSize: 11 }}>
              vendor self-attestation — per-option data locations and the
              exhaustive egress list; not a certification
            </span>
          </div>
          <p className="mut" style={{ fontSize: 12, margin: 0 }}>
            More detail lives in{" "}
            <Link href="/account">Account &amp; security</Link> (roles, MFA and
            session policy) and the honest{" "}
            <Link href="/roadmap">roadmap</Link> (what is not built yet, with
            target quarters).
          </p>
        </div>
      )}
    </section>
  );
}
