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
import { useState } from "react";
import Link from "next/link";
import {
  ShieldCheck,
  MapPin,
  Users,
  ScrollText,
  ChevronDown,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";

interface TrustItem {
  icon: LucideIcon;
  label: string;
  // one-line summary shown on the strip face
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
    short: "Self-hosted — can stay in Canada",
    status: "live",
    detail:
      "ANDS Studio is self-hosted: you run it inside your own infrastructure, " +
      "so your dossiers and their data can remain on Canadian soil to meet " +
      "residency obligations. Nothing is sent to a shared multi-tenant cloud " +
      "we operate.",
  },
  {
    icon: ShieldCheck,
    label: "Tenant isolation",
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
    short: "Append-only, actor + UTC stamped, exportable",
    status: "live",
    detail:
      "Every change is written to an append-only audit trail — sequence-" +
      "numbered, actor- and workspace-stamped, with UTC timestamps and typed " +
      "override reasons — and is exportable (CSV / JSON) for inspection " +
      "binders. It is designed to be tamper-evident, not editable after the " +
      "fact.",
  },
  {
    icon: ShieldCheck,
    label: "SOC 2 / SSO / SCIM",
    short: "On the roadmap — not certified / not built yet",
    status: "roadmap",
    detail: (
      <>
        Being honest: we are <b>not</b> SOC 2 certified today, and enterprise{" "}
        single sign-on (SAML / OIDC) and SCIM provisioning are{" "}
        <b>not built yet</b>. Accounts today are per-workspace email + password
        with TOTP MFA (and an optional workspace-wide MFA mandate). These items
        have stated target quarters on the{" "}
        <Link href="/roadmap">roadmap</Link> — we would rather you plan around a
        real date than assume a control exists.
      </>
    ),
  },
];

// A persistent, honest "Trust & security" strip mounted on the hero. Replaces
// the vague "progress saved automatically" footnote. Progressive disclosure:
// the four live pillars + one honest roadmap pillar read at a glance; the
// one-page security summary opens on demand.
export function TrustStrip() {
  const [open, setOpen] = useState(false);
  return (
    <section
      className="card glass trust-strip"
      aria-label="Trust and security"
      style={{
        marginTop: 22,
        padding: "14px 18px",
        textAlign: "left",
        maxWidth: 760,
        marginInline: "auto",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <b style={{ fontSize: 14 }}>Trust &amp; security</b>
        <span className="mut" style={{ fontSize: 12 }}>
          the questions your auditor asks first — answered plainly
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

      {/* the four live pillars + one honest roadmap pillar, scannable */}
      <ul
        style={{
          listStyle: "none",
          margin: "10px 0 0",
          padding: 0,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
          gap: 8,
        }}
      >
        {ITEMS.map(({ icon: Icon, label, short, status }) => (
          <li
            key={label}
            style={{ display: "flex", gap: 8, alignItems: "flex-start" }}
          >
            <Icon size={15} aria-hidden />
            <span style={{ fontSize: 12.5, lineHeight: 1.35 }}>
              <b>{label}</b>
              {status === "roadmap" && (
                <span
                  className="chip"
                  style={{ marginLeft: 6, fontSize: 10, padding: "0 6px" }}
                >
                  roadmap
                </span>
              )}
              <br />
              <span className="mut">{short}</span>
            </span>
          </li>
        ))}
      </ul>

      {open && (
        <div
          className="disclosure-body"
          style={{ marginTop: 12, display: "grid", gap: 10 }}
        >
          <p className="mut" style={{ fontSize: 12, margin: 0 }}>
            This is a plain-language summary of how ANDS Studio handles your
            data and controls. It is not a certification. Where a control is not
            yet built we say so.
          </p>
          {ITEMS.map(({ label, detail, status }) => (
            <div key={label} style={{ fontSize: 12.5, lineHeight: 1.45 }}>
              <b>{label}</b>
              {status === "roadmap" && (
                <span
                  className="chip"
                  style={{ marginLeft: 6, fontSize: 10, padding: "0 6px" }}
                >
                  roadmap
                </span>
              )}
              <div className="mut" style={{ marginTop: 2 }}>
                {detail}
              </div>
            </div>
          ))}
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
