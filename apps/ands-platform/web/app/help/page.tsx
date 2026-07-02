"use client";
// Regulatory reference — the panel's most-requested missing surface:
// "add prominent links to documentation or help resources" (onboarding),
// "add a 'Regulatory Reference' section with links to Health Canada's
// guidance documents" (operations). Same sources the in-app Health Canada
// content review cites.
import Link from "next/link";
import { UserChip } from "@/components/UserChip";

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

export default function HelpPage() {
  return (
    <>
      <header className="topbar">
        <span className="brand">
          <span className="dot" aria-hidden />
          ANDS&nbsp;Studio <small>· regulatory reference</small>
        </span>
        <span className="spacer" />
        <UserChip />
        <Link className="chip" href="/dossiers">Dossier manager</Link>
        <Link className="chip" href="/portfolio">Portfolio</Link>
        <Link className="chip" href="/">Guided journey →</Link>
      </header>
      <main className="dossier-home">
        <h1>Regulatory reference</h1>
        <p className="mut" style={{ maxWidth: "68ch" }}>
          The primary Health Canada sources behind everything this app checks
          and generates. Every in-app review finding links to one of these;
          this page collects them so you can read the rule, not just trust the
          tool. All links go to canada.ca / laws-lois.justice.gc.ca.
        </p>
        {SECTIONS.map((s) => (
          <section key={s.title} style={{ marginTop: 18 }}>
            <h2 style={{ fontSize: 16 }}>{s.title}</h2>
            <div style={{ display: "grid", gap: 10, marginTop: 8 }}>
              {s.items.map((it) => (
                <a key={it.href} className="card glass" href={it.href}
                  target="_blank" rel="noopener noreferrer"
                  style={{ padding: "12px 16px", display: "block" }}>
                  <div style={{ fontWeight: 600 }}>{it.label} ↗</div>
                  <div className="mut" style={{ fontSize: 13, marginTop: 2 }}>
                    {it.note}
                  </div>
                </a>
              ))}
            </div>
          </section>
        ))}
        <p className="mut" style={{ fontSize: 12, marginTop: 20 }}>
          Tip: dashed-underlined terms across the app reveal plain-language
          definitions on hover — and every Health Canada content-review
          finding cites its source directly.
        </p>
      </main>
    </>
  );
}
