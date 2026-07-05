"use client";
// Regulatory reference — the panel's most-requested missing surface:
// "add prominent links to documentation or help resources" (onboarding),
// "add a 'Regulatory Reference' section with links to Health Canada's
// guidance documents" (operations). Same sources the in-app Health Canada
// content review cites.
import { useEffect, useState, type ReactNode } from "react";
import { TopNav } from "@/components/TopNav";
import Link from "next/link";
import { CriteriaSyncHistory } from "@/components/dossier/CriteriaSyncHistory";

type Rule = { rule: string; rule_id: string; family: string;
  severity: string; description: string };

const APPS =
  "https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions";

const SECTIONS: { title: string; items: { label: string; href: string; note: string }[] }[] = [
  {
    title: "Filing an ANDS — the core references",
    items: [
      { label: "Canadian Module 1 — organization & document placement",
        href: `${APPS}/guidance-documents/organization-document-placement-canadian-module-1.html`,
        note: "What goes where in Module 1 — the structure this app builds for you." },
      { label: "Regulatory Enrolment Process (REP)",
        href: "https://health-products.canada.ca/rep-pir/index.html",
        note: "Where Company IDs and Dossier IDs come from; the templates that enrol your company and product." },
      { label: "eCTD guidance — preparation of drug regulatory activities",
        href: `${APPS}/guidance-documents/ectd/preparation-drug-submissions-applications-electronic-common-technical-document.html`,
        note: "The electronic format rules this app validates against (v5.3-era rules)." },
      { label: "Forms index (Health Canada drug submissions)",
        href: `${APPS}/forms.html`,
        note: "All official submission forms, including Form V." },
    ],
  },
  {
    title: "Generic-specific",
    items: [
      { label: "PM(NOC) Regulations (SOR/93-133)",
        href: "https://laws-lois.justice.gc.ca/eng/regulations/SOR-93-133/",
        note: "Patent linkage: Form V declarations, Notices of Allegation, the 45-day window and the 24-month stay." },
      { label: "Comparative bioavailability — conduct & analysis",
        href: `${APPS}/guidance-documents/bioavailability-bioequivalence/conduct-analysis-comparative.html`,
        note: "The CS-BE evidence rules — AUC and Cmax 90% confidence intervals vs 80.00–125.00%." },
      { label: "Quality (CTD) templates incl. QOS-CE",
        href: `${APPS}/templates.html`,
        note: "Quality Overall Summary templates the in-app author follows." },
    ],
  },
  {
    title: "Transmitting & after approval",
    items: [
      { label: "Common Electronic Submissions Gateway (CESG)",
        href: `${APPS}/guidance-documents/common-electronic-submissions-gateway.html`,
        note: "How packages reach Health Canada — via the FDA ESG with HC as the centre. This app prepares and simulates; the gateway account is yours." },
      { label: "Fees for drug submissions",
        href: "https://www.canada.ca/en/health-canada/services/drugs-health-products/funding-fees/fees-respect-drugs-medical-devices.html",
        note: "Review fees, the small-business reduction and first-submission waiver the fees step applies." },
      { label: "Drug Identification Number (DIN) — annual obligations",
        href: "https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/fact-sheets/drug-identification-number.html",
        note: "Annual notification and Right-to-Sell — tracked in Registry." },
    ],
  },
];

// A single labelled rule-ID row, so the validation catalogue reads as an
// aligned code / description grid rather than a run-on paragraph list.
function RuleIdRow({ code, extra, children }:
  { code: string; extra?: string; children: ReactNode }) {
  return (
    <li style={{ display: "grid",
      gridTemplateColumns: "minmax(120px, max-content) 1fr",
      gap: "10px 16px", alignItems: "baseline", margin: "8px 0" }}>
      <span style={{ whiteSpace: "nowrap" }}>
        <code>{code}</code>{extra}
      </span>
      <span>{children}</span>
    </li>
  );
}

export default function HelpPage() {
  const [rules, setRules] = useState<Rule[] | null>(null);
  useEffect(() => {
    fetch("/api/dossier/validation/rules", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => setRules(b?.rules || []))
      .catch(() => setRules([]));
  }, []);
  const families: Record<string, Rule[]> = {};
  for (const r of rules || []) (families[r.family] ||= []).push(r);
  return (
    <>
      <TopNav subtitle="regulatory reference" />
      <main className="dossier-home" style={{ maxWidth: 860 }}>
        <h1>Regulatory reference</h1>
        <p className="lede">
          The primary Health Canada sources behind everything this app checks
          and generates. Every in-app review finding links to one of these;
          this page collects them so you can read the rule, not just trust the
          tool. All links go to canada.ca / laws-lois.justice.gc.ca.
        </p>

        {SECTIONS.map((s) => (
          <section key={s.title} style={{ marginTop: 34 }}>
            <h2>{s.title}</h2>
            <div style={{ display: "grid", gap: 12, marginTop: 12 }}>
              {s.items.map((it) => (
                <a key={it.href} className="card glass" href={it.href}
                  target="_blank" rel="noopener noreferrer"
                  style={{ padding: "16px 18px", display: "block" }}>
                  <div style={{ fontWeight: 600, fontSize: 15,
                    lineHeight: 1.4 }}>
                    {it.label} ↗
                  </div>
                  <div className="mut" style={{ fontSize: 14, marginTop: 5 }}>
                    {it.note}
                  </div>
                </a>
              ))}
            </div>
          </section>
        ))}

        {/* ── How validation works ────────────────────────────────────── */}
        <section style={{ marginTop: 40 }}>
          <h2>How validation works here</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <p style={{ margin: 0 }}>
              Every finding carries a rule ID you can cite in review meetings:
            </p>
            <ul style={{ margin: "12px 0 0", padding: 0, listStyle: "none" }}>
              <RuleIdRow code="CA-E-1xxx">
                leaf inventory integrity: every live document needs an href and
                a well-formed MD5 checksum; duplicate leaf IDs are errors.
              </RuleIdRow>
              <RuleIdRow code="CA-E-2xxx">
                lifecycle legality: replace/append/delete operations must
                reference a real prior leaf; new leaves can&apos;t claim one.
              </RuleIdRow>
              <RuleIdRow code="CA-E-3xxx">
                file/folder naming hygiene (lowercase, no spaces, module folder
                placement).
              </RuleIdRow>
              <RuleIdRow code="CA-E-4xxx">
                sequence numbering.
              </RuleIdRow>
              <li style={{ margin: "8px 0" }}>
                XML backbone (index + CA regional) and PDF conformance run in
                the full technical check on the stored bytes.
              </li>
              <RuleIdRow code="CA-REP-0001">
                filing is blocked while a dossier still uses a placeholder ID
                instead of the REP-issued one.
              </RuleIdRow>
            </ul>
            <p className="mut" style={{ margin: "14px 0 0", fontSize: 14 }}>
              On top of the technical layer, each authorable form has a
              content review against Health Canada&apos;s required elements —
              every finding cites its canada.ca source and proposes the edit.
            </p>
          </div>

          {/* the live catalogue itself — pulled from the validation engine,
              not hand-maintained copy, so it can never drift from reality */}
          <div className="card glass" style={{ padding: "18px 22px",
            marginTop: 14 }}>
            <h3 style={{ margin: "0 0 6px" }}>
              The complete rule catalogue
              {rules ? ` (${rules.length} rules, live from the engine)` : ""}
            </h3>
            {rules === null ? (
              <div className="mut" style={{ marginTop: 6 }}>Loading…</div>
            ) : (
              <div style={{ display: "grid", gap: 6 }}>
                {Object.entries(families).map(([fam, rs]) => (
                  <details key={fam}>
                    <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                      {fam} — {rs.length} rule{rs.length === 1 ? "" : "s"}
                    </summary>
                    <ul style={{ margin: "8px 0 4px", paddingLeft: 20 }}>
                      {rs.map((r) => (
                        <li key={r.rule_id} style={{ margin: "5px 0",
                          lineHeight: 1.5 }}>
                          <code>{r.rule_id}</code>
                          {r.severity === "warning" ? " (warning)" : ""} —{" "}
                          {r.description}
                        </li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* CAMP-CRITERIA-SYNC: the auditable proof the ruleset stays synced to
            Health Canada's criteria versions — review cadence + append-only
            version history, live from the validation engine. */}
        <section style={{ marginTop: 40 }}>
          <h2>How the ruleset stays synced to Health Canada&apos;s criteria</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <CriteriaSyncHistory open />
          </div>
        </section>

        {/* ── AI drafting controls ────────────────────────────────────── */}
        <section style={{ marginTop: 40 }}>
          <h2>How AI drafting is controlled</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <ul style={{ margin: 0, paddingLeft: 22, display: "grid",
              gap: 10, lineHeight: 1.55 }}>
              <li>Opt-in, per section — only sections marked <b>✦AI</b> offer it,
                and the standard template author is always available instead.</li>
              <li>Nothing is saved until you click <i>Use this draft</i>; the
                assistant asks for missing facts rather than inventing them.</li>
              <li>Every AI-assisted document is permanently labeled
                (<i>AI-assisted — review before filing</i>) and recorded as such
                in the append-only audit trail — provenance never disappears.</li>
              <li>Drafts go through the same Health Canada content review and
                eCTD validation as any other document, and the human review +
                e-signature gate still stands between any document and
                transmission.</li>
            </ul>
          </div>
        </section>

        <p className="mut" style={{ fontSize: 13, marginTop: 28 }}>
          Tip: dashed-underlined terms across the app reveal plain-language
          definitions on hover — and every Health Canada content-review
          finding cites its source directly.
        </p>
      </main>
    </>
  );
}
