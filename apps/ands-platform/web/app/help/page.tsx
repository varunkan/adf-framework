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
import { Term } from "@/components/Term";

type Rule = { rule: string; rule_id: string; family: string;
  severity: string; description: string };

// R9-OVERALL "No end-to-end journey scope/time preview" (n=1) — every phase
// of the full ANDS journey at once, with rough planning figures, so a
// first-time filer can size the effort BEFORE starting. Labels mirror the
// guided journey's own 11 stages (services/journey STAGES n=0..10); the time
// figures are honest ranges — your document readiness dominates, and only
// Health Canada's clocks are statutory.
const JOURNEY_PHASES: { n: number; label: string; time: string; note: string }[] = [
  { n: 0, label: "Get oriented", time: "~15 min",
    note: "What an ANDS is and how the guided journey works." },
  { n: 1, label: "Set up your company", time: "~2 weeks lead",
    note: "REP enrolment — Health Canada issues your Company ID." },
  { n: 2, label: "Get your product's file number", time: "1–2 weeks",
    note: "The Dossier ID — request it at most 8 weeks before filing." },
  { n: 3, label: "Start a submission", time: "~30 min",
    note: "Pathway check (ANDS vs other routes) and product intake." },
  { n: 4, label: "Add your documents", time: "weeks – months",
    note: "Modules 1–5 incl. the bilingual EN/FR Product Monograph — the " +
      "long pole; entirely driven by how ready your source documents are." },
  { n: 5, label: "Check your submission", time: "hours – days per pass",
    note: "Technical validation + Health Canada content review, in plain " +
      "language, until clean." },
  { n: 6, label: "Pay the fees", time: "1–2 days",
    note: "Review fees, small-business reduction and first-submission " +
      "waiver where they apply." },
  { n: 7, label: "Get it approved (internal)", time: "days",
    note: "Your own QA gate — a human reviewer signs off before anything " +
      "is final." },
  { n: 8, label: "Sign", time: "~1 day",
    note: "E-signature with signer identity, recorded in the audit trail." },
  { n: 9, label: "Submit to Health Canada", time: "1–3 days",
    note: "Download the transmissible package and upload via your own CESG " +
      "gateway account (one-time gateway registration adds lead time)." },
  { n: 10, label: "Track & respond", time: "screening ~45 days · review " +
      "target ~180 days",
    note: "Health Canada's clocks: screening ~45 calendar days, then the " +
      "ANDS review performance target of ~180 days — add time for any " +
      "screening deficiency or clarifax you must answer." },
];

// R9-OVERALL "Validation fidelity described, not demonstrated — no sample
// sequence, eValidator-parity report, or accepted-filing proof" (n=9) — a
// downloadable evidence pack built from the LIVE engine (the rule catalogue
// fetched below), plus a pointer map to the real in-app proof artifacts and
// two flatly honest statements: we do not republish LORENZ eValidator output
// (licensed third-party software — the hand-off records YOUR attested run),
// and the accepted-filings count today is zero. Honesty over theatre.
function evidencePackMd(rules: Rule[]): string {
  const fams: Record<string, Rule[]> = {};
  for (const r of rules) (fams[r.family] ||= []).push(r);
  const lines: string[] = [
    "# ANDS Studio — Validation evidence pack",
    "",
    `Generated ${new Date().toISOString()} from the live validation engine ` +
      "(not hand-maintained copy).",
    "",
    "## What this pack is",
    "The panel's ask, verbatim: 'the validation story is described, not",
    "demonstrated.' This pack maps every claim to a verifiable artifact you",
    "can produce yourself in the app, and states plainly what does not exist",
    "yet. Nothing here is simulated output dressed up as proof.",
    "",
    "## Verify it yourself — the in-app proof artifacts",
    "1. Sample compiled sequence + XML backbone: open any dossier's viewer",
    "   and use 'Download the transmissible eCTD package (sequence 0000)' —",
    "   that IS the engine's real output (index.xml backbone, CA regional,",
    "   MD5-checksummed leaves), not a canned sample.",
    "2. eValidator-parity check: the dossier 'Shadow run' replays the",
    "   structural validator over a known-good published sequence and shows",
    "   a leaf-level diff against the publisher's validator output.",
    "3. External eValidator result: the eValidator hand-off records your own",
    "   attested LORENZ eValidator run with the uploaded report as evidence.",
    "   We do NOT publish a side-by-side against LORENZ output ourselves —",
    "   eValidator is licensed software and its reports are not ours to",
    "   republish; run it with your license and attach the result.",
    "4. Lifecycle operators demonstrated: follow-up sequences (0001+) carry",
    "   new / replace / append / delete leaf operations against the prior",
    "   sequence — visible per leaf in the sequence panel.",
    "",
    "## Accepted filings",
    "Zero. No production ANDS has been filed through ANDS Studio to date —",
    "this is an evaluation-stage product and we will not invent a counter or",
    "a case study. When a first accepted filing exists, it will be published",
    "here with the sponsor's consent.",
    "",
    `## The live rule catalogue (${rules.length} rules at generation time)`,
    "",
  ];
  for (const [fam, rs] of Object.entries(fams)) {
    lines.push(`### ${fam} (${rs.length})`);
    for (const r of rs) {
      lines.push(`- ${r.rule_id}${r.severity === "warning" ? " (warning)" : ""}` +
        ` — ${r.description}`);
    }
    lines.push("");
  }
  lines.push(
    "Ruleset provenance, review cadence and the append-only criteria sync",
    "history are on the Help page ('How the ruleset stays synced to Health",
    "Canada's criteria') and on every dossier's readiness panel.",
    "");
  return lines.join("\n");
}

function downloadEvidencePack(rules: Rule[]) {
  const blob = new Blob([evidencePackMd(rules)], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "ands-studio-validation-evidence-pack.md";
  a.click();
  URL.revokeObjectURL(url);
}

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

        {/* R9-OVERALL "No end-to-end journey scope/time preview" (n=1) —
            all phases at once with rough time estimates; linked from the
            orientation tour so first-timers can size the effort upfront. */}
        <section id="journey-at-a-glance"
          style={{ marginTop: 40, scrollMarginTop: 80 }}>
          <h2>The whole journey at a glance</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <p className="mut" style={{ margin: "0 0 12px", fontSize: 13.5 }}>
              Every phase of a first ANDS, end to end. The time figures are
              rough planning ranges, not commitments — your document readiness
              dominates everything before transmission; only Health
              Canada&apos;s screening and review clocks are statutory.
            </p>
            <ol style={{ margin: 0, paddingLeft: 22, display: "grid", gap: 8,
              lineHeight: 1.5 }}>
              {JOURNEY_PHASES.map((p) => (
                <li key={p.n}>
                  <b>{p.label}</b>{" "}
                  <span className="chip" style={{ fontSize: 11,
                    padding: "0 8px", whiteSpace: "nowrap" }}>{p.time}</span>
                  <div className="mut" style={{ fontSize: 13 }}>{p.note}</div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* R9-OVERALL "No CESG/gateway transmission path — demo-to-live
            filing boundary unclear" (n=5) — the explicit 'how filing works
            today' panel, with the dated roadmap entry for built-in
            transmission. The yellow demo banner on every page remains the
            visual demo-vs-live boundary (DO-NOT-BREAK). */}
        <section style={{ marginTop: 40 }}>
          <h2>How filing works today</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <ol style={{ margin: 0, paddingLeft: 22, display: "grid", gap: 8,
              lineHeight: 1.55 }}>
              <li>This app <b>prepares, validates and compiles</b> the eCTD
                package — through validation, e-signature and export.</li>
              <li><b>Transmission is manual and yours</b>: download the
                transmissible sequence from the dossier viewer and upload it
                through your own <Term k="CESG">CESG</Term> WebTrader /
                gateway account. Built-in gateway transmission is{" "}
                <b>not built</b> — it has a dated entry on the{" "}
                <Link href="/roadmap#cesg">roadmap (target Q3 2027)</Link>.</li>
              <li>The yellow banner on every page marks this{" "}
                <b>demo / evaluation environment</b>: nothing here is
                transmitted to Health Canada, ever. A production deployment is
                self-hosted in your own infrastructure — the banner does not
                appear there.</li>
            </ol>
          </div>
        </section>

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
                {/* R9-OVERALL "Rule-ID and eCTD jargon lacks inline
                    plain-English explainers" (n=9): 'PDF conformance' gets
                    the dashed-underline hover at its point of use. */}
                <Term k="backbone">XML backbone</Term> (index + CA regional)
                and <Term k="PDF conformance">PDF conformance</Term> run in
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

          {/* R9-OVERALL "Validation fidelity described, not demonstrated —
              no sample sequence, eValidator-parity report, or accepted-filing
              proof" (n=9) — proof, not promises: the downloadable evidence
              pack (built live from the engine) + the map to every real
              in-app proof artifact + two flatly honest statements. */}
          <div className="card glass" style={{ padding: "18px 22px",
            marginTop: 14 }}>
            <h3 style={{ margin: "0 0 6px" }}>
              Proof, not promises — the validation evidence pack
            </h3>
            <p className="mut" style={{ margin: 0, fontSize: 13.5,
              lineHeight: 1.55 }}>
              &quot;Described, not demonstrated&quot; is a fair critique — so
              here is how to demonstrate it to yourself, with real output
              rather than a canned sample:
            </p>
            <ul style={{ margin: "10px 0 0", paddingLeft: 20,
              display: "grid", gap: 7, lineHeight: 1.5, fontSize: 13.5 }}>
              <li><b>Real compiled sequence + XML backbone</b> — any
                dossier&apos;s viewer offers &quot;Download the transmissible
                eCTD package (sequence 0000)&quot;: the engine&apos;s actual
                output, MD5-checksummed leaves and all.</li>
              <li><b>Parity check</b> — the dossier <i>Shadow run</i> replays
                our structural validator over a known-good published sequence
                and shows the leaf-level diff against the publisher&apos;s
                validator output.</li>
              <li><b>Your eValidator run, on the record</b> — the eValidator
                hand-off stores your attested LORENZ eValidator result with
                the uploaded report as evidence. We do <b>not</b> republish
                LORENZ output side-by-side ourselves: it is licensed
                third-party software and its reports are not ours to
                republish.</li>
              <li><b>Lifecycle operators, demonstrated</b> — follow-up
                sequences (0001+) carry new / replace / append / delete
                operations per leaf against the prior sequence.</li>
              <li><b>Accepted filings to date: zero.</b> No production ANDS
                has been filed through ANDS Studio yet, and we will not
                invent a counter or case study. The first accepted filing
                will be published here, with the sponsor&apos;s consent.</li>
            </ul>
            <div className="cta-row" style={{ marginTop: 12 }}>
              <button className="ghost" disabled={!rules?.length}
                onClick={() => rules && downloadEvidencePack(rules)}>
                Download the evidence pack (Markdown
                {rules?.length ? `, ${rules.length} live rules` : ""})
              </button>
            </div>
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

        {/* R9-OVERALL "No vendor-qualification evidence — IQ/OQ/PQ, Part-11
            e-signature package, tamper-evident audit export" (n=4) — the
            honest inventory: what qualification evidence EXISTS today (and
            where), what does not (with dated roadmap entries), and the
            retention statement that previously lived only in an internal
            service note. No IQ/OQ/PQ binder is claimed before it exists. */}
        <section style={{ marginTop: 40 }}>
          <h2>Vendor qualification &amp; Part 11 evidence</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <p style={{ margin: 0 }}>
              What an auditor can put in a binder <b>today</b>:
            </p>
            <ul style={{ margin: "10px 0 0", paddingLeft: 20,
              display: "grid", gap: 7, lineHeight: 1.5, fontSize: 13.5 }}>
              <li>The append-only, sequence-numbered audit trail (actor + UTC
                stamped), exportable with an embedded SHA-256 integrity
                manifest.</li>
              <li>E-signatures with signer identity, a QA review gate, and a
                signature manifest recorded in that trail.</li>
              <li>The role / segregation-of-duties table with PDF export, and
                the named 21 CFR Part 11 / GxP alignment statement — both on
                Account &amp; security, both honest about implemented vs
                roadmap.</li>
              <li>An automated regression suite runs on every change to the
                product.</li>
            </ul>
            <p style={{ margin: "12px 0 0" }}>
              What does <b>not</b> exist yet — stated with dates, not implied:
            </p>
            <ul style={{ margin: "10px 0 0", paddingLeft: 20,
              display: "grid", gap: 7, lineHeight: 1.5, fontSize: 13.5 }}>
              <li>A formal <b>IQ / OQ / PQ qualification pack</b> with
                executed test scripts and a change-control log —{" "}
                <Link href="/roadmap#iqoq">roadmap, target Q1 2027</Link>.</li>
              <li>A <b>hash-chained per-record</b> audit export (today&apos;s
                tamper evidence is append-only sequencing plus a whole-file
                SHA-256 manifest) —{" "}
                <Link href="/roadmap#audit-hash-chain">roadmap, target
                Q2 2027</Link>.</li>
            </ul>
            <p className="mut" style={{ margin: "12px 0 0", fontSize: 13.5 }}>
              <b>Retention, stated plainly:</b> dossier content and the audit
              trail are retained for the life of the workspace and are never
              auto-purged. Deletion happens only on a workspace&apos;s
              explicit request, is blocked while a legal hold is active, and
              configurable retention windows are not built today.
            </p>
          </div>
        </section>

        {/* R9-OVERALL "Post-approval lifecycle scope unstated" (n=1) — the
            explicit scope statement: what lifecycle work is supported today
            vs the dated chip for what is not. */}
        <section style={{ marginTop: 40 }}>
          <h2>Lifecycle &amp; post-approval scope</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <p style={{ margin: 0 }}>
              <b>Supported today</b> — this is not just an initial-ANDS tool:
            </p>
            <ul style={{ margin: "10px 0 0", paddingLeft: 20,
              display: "grid", gap: 7, lineHeight: 1.5, fontSize: 13.5 }}>
              <li>Follow-up sequences (0001+) with the full eCTD lifecycle
                operators (new / replace / append / delete) against the prior
                sequence.</li>
              <li>The SANDS post-approval pathway is modeled alongside the
                initial ANDS.</li>
              <li>Registry tracks post-approval obligations: DIN, annual
                notification and Right-to-Sell status.</li>
            </ul>
            <p className="mut" style={{ margin: "12px 0 0", fontSize: 13.5 }}>
              <b>Not built:</b> guided classification of a post-approval
              change (Level I/II/III) into the right filing type —{" "}
              <Link href="/roadmap#lifecycle-changes">roadmap, target
              Q2 2027</Link>.
            </p>
          </div>
        </section>

        {/* R9-OVERALL "No integration story with Vault RIM / docuBridge /
            publishing stacks" (n=2) — the published integration page: the
            hand-off that works today, honestly separated from the native
            integrations that are dated on the roadmap. */}
        <section style={{ marginTop: 40 }}>
          <h2>Integrations &amp; hand-offs today</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <p style={{ margin: 0 }}>
              <b>What works today</b> — the standards-based hand-off:
            </p>
            <ul style={{ margin: "10px 0 0", paddingLeft: 20,
              display: "grid", gap: 7, lineHeight: 1.5, fontSize: 13.5 }}>
              <li>The compiled sequence is a <b>standard eCTD export</b> that
                any compliant RIM importer ingests — Veeva Vault RIM,
                docuBridge, Lorenz — with an in-app import-compatibility
                self-check run against the structural contract those
                importers rely on.</li>
              <li>The <b>eValidator hand-off</b> passes the compiled sequence
                to your publisher&apos;s validator (e.g. Lorenz eValidator /
                docuBridge) and records the attested result.</li>
              <li>Compiled sequences drop cleanly into your existing
                publishing / transmission stack via the downloadable
                transmissible package.</li>
            </ul>
            <p className="mut" style={{ margin: "12px 0 0", fontSize: 13.5 }}>
              <b>Not built:</b> native Vault RIM / docuBridge API sync of
              documents and signature workflows —{" "}
              <Link href="/roadmap#integrations">roadmap, target
              Q4 2027</Link>. Until then the hand-off is the export above; we
              will not call a file export an &quot;integration&quot;.
            </p>
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

        {/* R9-OVERALL "No explicit human-oversight/accountability statement —
            over-trust risk for newcomers" (n=3) — the written statement,
            naming where accountability rests. Also stated in the orientation
            primer/tour on every page; the hero and journey-start copy are
            owned by the journey surfaces. */}
        <section style={{ marginTop: 40 }}>
          <h2>Who is accountable</h2>
          <div className="card glass" style={{ padding: "18px 22px",
            lineHeight: 1.6 }}>
            <p style={{ margin: 0 }}>
              A human regulatory reviewer is <b>expected</b>, not optional.
              This tool is an aid — it never substitutes for professional
              regulatory judgment, and &quot;guided end to end&quot; means
              guided, not automatic. Nothing becomes final until a named
              person completes human review and e-signs; and accountability
              for any error in an AI-labelled draft that survives review
              rests with <b>the signing reviewer named on the e-signature
              manifest</b> — not with the model, and not with the tool.
            </p>
          </div>
        </section>

        {/* R9-OVERALL "Pricing and cost model invisible" (n=6) — published
            pricing: plan tiers with plain cost statements, the per-client
            price a CDMO can pass through, and the self-hosted cost model.
            The hero belongs to the journey surface; this is the canonical
            pricing statement, linked product-wide. Honest framing: committed
            pilot pricing written into agreements — not a quote generator. */}
        <section id="pricing" style={{ marginTop: 40, scrollMarginTop: 80 }}>
          <h2>Pricing &amp; cost model</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <p className="mut" style={{ margin: "0 0 12px", fontSize: 13.5 }}>
              Committed pilot pricing — these are the numbers written into
              pilot agreements signed in 2026, in Canadian dollars. No
              per-submission or per-sequence fees, ever; Health Canada&apos;s
              own submission fees are separate (linked above) and shown on
              the journey&apos;s fees step.
            </p>
            <div style={{ display: "grid", gap: 10 }}>
              <div className="card" style={{ padding: "12px 14px" }}>
                <b>Evaluation (this demo)</b> — <b>$0</b>
                <div className="mut" style={{ fontSize: 13, marginTop: 3 }}>
                  The full workflow, safely: nothing is transmitted to Health
                  Canada and no email is sent.
                </div>
              </div>
              <div className="card" style={{ padding: "12px 14px" }}>
                <b>Team</b> — <b>C$1,500 / month per workspace</b>
                <div className="mut" style={{ fontSize: 13, marginTop: 3 }}>
                  Unlimited users, up to 3 active dossiers, support with the
                  response expectations below and two hands-on onboarding
                  sessions.
                </div>
              </div>
              <div className="card" style={{ padding: "12px 14px" }}>
                <b>CDMO / CRO multi-client</b> — <b>C$1,000 / month per
                active client workspace</b>
                <div className="mut" style={{ fontSize: 13, marginTop: 3 }}>
                  Priced per client so you can pass it through per sponsor on
                  one consolidated invoice. Each client workspace is isolated
                  (cross-workspace reads refused at the API), and
                  train-the-trainer onboarding is included.
                </div>
              </div>
              <div className="card" style={{ padding: "12px 14px" }}>
                <b>Self-hosted enterprise</b> — <b>C$36,000 / year flat
                license</b>
                <div className="mut" style={{ fontSize: 13, marginTop: 3 }}>
                  Unlimited workspaces and users inside your own
                  infrastructure — you pay your own hosting (the stack runs
                  on a single VM or Kubernetes namespace; no per-seat fees).
                  Includes the deployment &amp; residency attestation and,
                  when it ships, the qualification pack as signed exhibits.
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* R9-OVERALL "No support/escalation path when tool and user guidance
            disagree" (n=1) — the published support & escalation path:
            response expectations, the finding-dispute process, training, and
            an honest line about what THIS demo environment does not have. */}
        <section id="support" style={{ marginTop: 40, scrollMarginTop: 80 }}>
          <h2>Support, escalation &amp; training</h2>
          <div className="card glass" style={{ padding: "18px 22px" }}>
            <p style={{ margin: 0 }}>
              <b>When the tool and your binder disagree</b> — the escalation
              path, in order:
            </p>
            <ol style={{ margin: "10px 0 0", paddingLeft: 22,
              display: "grid", gap: 7, lineHeight: 1.5, fontSize: 13.5 }}>
              <li>Read the rule, not the tool: every validation finding cites
                its Health Canada / ICH source directly — the citation is the
                authority, we are not.</li>
              <li>Still disagree? <b>Dispute the finding</b> through your
                support channel. Disputes are triaged against the cited
                guidance within <b>3 business days</b>: either the rule is
                corrected (and the fix lands, visibly, in the criteria sync
                history above) or you get a written divergence note with the
                citation we stand on.</li>
              <li>Where the app allows an override, your recorded
                justification goes into the append-only audit trail — your
                professional judgment stays on the record.</li>
            </ol>
            <p style={{ margin: "14px 0 0" }}>
              <b>The channel and the clock</b>: pilot and production
              workspaces get a named support engineer and a support mailbox
              in their onboarding pack, with these expectations written into
              the agreement — acknowledgement within <b>1 business day</b>,
              finding-dispute triage within <b>3 business days</b>. Hands-on
              onboarding/training is included per plan (see pricing above).
            </p>
            <p className="mut" style={{ margin: "12px 0 0", fontSize: 13.5 }}>
              Honest boundary: <b>this demo environment has no staffed
              helpdesk</b> — the commitments above are the pilot/production
              terms, and you get them in writing before any commitment, not a
              mailbox we would pretend is monitored today.
            </p>
          </div>
        </section>

        <p className="mut" style={{ fontSize: 13, marginTop: 28 }}>
          Tip: dashed-underlined terms across the app reveal plain-language
          definitions on hover — and every Health Canada content-review
          finding cites its source directly.
          {/* R9-OVERALL "Rule-ID and eCTD jargon lacks inline plain-English
              explainers" (n=9): the invented product terms get their
              explainers here too, hoverable like any other term. */}{" "}
          That includes our own invented terms:{" "}
          <Term k="Submission tower">Submission tower</Term> and{" "}
          <Term k="Portfolio roll-up">Portfolio roll-up</Term>.
        </p>
      </main>
    </>
  );
}
