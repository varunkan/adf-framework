// WS4.3 — public, honest roadmap. Linked from the sign-in card's SSO affordance
// (/roadmap#sso) and mirrored in the Account page Roadmap card. States target
// quarters plainly and never implies a not-yet-built capability works today.
import Link from "next/link";
import { ROADMAP, type RoadmapEntry } from "@/lib/roadmap";

export const metadata = { title: "Roadmap · ANDS Studio" };

// Round-9 `overall` backlog — the panel's procurement/adoption gates each need
// a DATED, honest entry rather than a bare "roadmap" label. Page-local so the
// shared lib entries (rendered on Account too) stay untouched. Same honesty
// rule: stated targets, not shipped features; today is 2026-07-07.
const R9_ENTRIES: RoadmapEntry[] = [
  // R9-OVERALL "SOC 2 / SSO / SCIM absent — procurement hard stop with no
  // dated path" (n=15): the dated SOC 2 Type II commitment + current stage.
  {
    id: "soc2",
    title: "SOC 2 Type II certification",
    targetQuarter: "Q3 2027 (report)",
    status: "in-design",
    detail:
      "We are not SOC 2 certified today, and we will not imply otherwise. " +
      "The dated path: current stage is pre-audit readiness (control mapping " +
      "and evidence collection; auditor not yet engaged) · Type I target " +
      "Q1 2027 · Type II observation window H1 2027 · report expected " +
      "Q3 2027. Note what already shipped ahead of this: OIDC single " +
      "sign-on is live per workspace (Account & security); SAML 2.0 and " +
      "SCIM 2.0 remain dated below (see the SSO and SCIM entries).",
  },
  // R9-OVERALL "No CESG/gateway transmission path — demo-to-live filing
  // boundary unclear" (n=5): the missing dated entry for built-in transmission.
  {
    id: "cesg",
    title: "Built-in CESG / gateway transmission",
    targetQuarter: "Q3 2027",
    status: "planned",
    detail:
      "How filing works today: the app prepares, validates and compiles the " +
      "eCTD package; you download the transmissible sequence and upload it " +
      "through your own CESG WebTrader / gateway account — the gateway " +
      "account is yours, and the yellow banner marks this demo environment " +
      "as non-transmitting. Built-in transmission (submit from the app via " +
      "your registered gateway credentials, with delivery receipts in " +
      "Correspondence) is targeted for Q3 2027.",
  },
  // R9-OVERALL "No integration story with Vault RIM / docuBridge / publishing
  // stacks" (n=2): dated entry for the native integrations that do NOT exist;
  // the standard-eCTD hand-off that DOES exist is described on Help.
  {
    id: "integrations",
    title: "Native Veeva Vault RIM / docuBridge integrations",
    targetQuarter: "Q4 2027",
    status: "planned",
    detail:
      "Today the hand-off is the standard, self-checked eCTD export any " +
      "compliant RIM importer (Veeva Vault RIM, docuBridge, Lorenz) ingests " +
      "— see 'Integrations & hand-offs today' on Help. Native API sync of " +
      "documents and signature workflows (push/pull without the export step) " +
      "is not built and is targeted for Q4 2027.",
  },
  // R9-OVERALL "No vendor-qualification evidence — IQ/OQ/PQ, Part-11
  // e-signature package, tamper-evident audit export" (n=4): dated entries
  // for the formal pack and the per-record tamper evidence.
  {
    id: "iqoq",
    title: "Vendor-qualification pack (IQ / OQ / PQ)",
    targetQuarter: "Q1 2027",
    status: "planned",
    detail:
      "A downloadable qualification pack: installation/operational/" +
      "performance qualification protocols with executed test scripts and a " +
      "change-control log. Today's honest evidence set — the automated " +
      "regression suite run on every change, the Part 11 / GxP alignment " +
      "statement, and the exportable role/segregation-of-duties table — is " +
      "inventoried on Help under 'Vendor qualification & Part 11 evidence'.",
  },
  {
    id: "audit-hash-chain",
    title: "Hash-chained (per-record tamper-evident) audit export",
    targetQuarter: "Q2 2027",
    status: "planned",
    detail:
      "Audit exports today carry a whole-file SHA-256 integrity manifest; " +
      "the trail itself is append-only and sequence-numbered. A per-record " +
      "hash chain (each entry cryptographically bound to the previous one) " +
      "in the export format is targeted for Q2 2027.",
  },
  // R9-OVERALL "Post-approval lifecycle scope unstated" (n=1): the dated chip
  // for the one lifecycle piece that is NOT supported today.
  {
    id: "lifecycle-changes",
    title: "Post-approval change classification guidance (Level I–III)",
    targetQuarter: "Q2 2027",
    status: "planned",
    detail:
      "Supported today: follow-up sequences (0001+) with the full lifecycle " +
      "operators, the SANDS post-approval pathway, and Registry tracking of " +
      "DIN / Right-to-Sell / annual-notification obligations. Not built: " +
      "guided classification of a post-approval change (Level I/II/III) into " +
      "the right filing type — targeted for Q2 2027.",
  },
];

const ALL_ENTRIES: RoadmapEntry[] = [R9_ENTRIES[0], ...ROADMAP,
  ...R9_ENTRIES.slice(1)];

export default function RoadmapPage() {
  return (
    <main className="dossier-home" style={{ maxWidth: 760 }}>
      <h1>Roadmap</h1>
      <p className="lede">
        What is not built yet, with honest target quarters. Anything listed here
        is <b>not available today</b>. We would rather you plan around a real
        date than discover a gap mid-filing.
      </p>

      <div style={{ display: "grid", gap: 16, marginTop: 28 }}>
        {ALL_ENTRIES.map((e) => (
          <section key={e.id} id={e.id} className="card glass"
            style={{ padding: "18px 22px", scrollMarginTop: 80 }}>
            <div style={{ display: "flex", justifyContent: "space-between",
              gap: 14, alignItems: "baseline", flexWrap: "wrap" }}>
              <h2 style={{ margin: 0, fontSize: 17 }}>{e.title}</h2>
              <span className="chip" style={{ whiteSpace: "nowrap" }}>
                Target {e.targetQuarter}
                {e.status === "in-design" ? " · in design" : " · planned"}
              </span>
            </div>
            <p className="mut" style={{ margin: "10px 0 0", fontSize: 14,
              lineHeight: 1.6 }}>
              {e.detail}
            </p>
            {/* R9-OVERALL "SOC 2 / SSO / SCIM absent — procurement hard stop
                with no dated path" (n=15): OIDC shipped ahead of the shared
                entry's target — state the shipped part rather than letting a
                stale "not built yet" line under-claim (honesty cuts both
                ways). Additive, dated, page-local. */}
            {e.id === "sso" && (
              <p style={{ margin: "10px 0 0", fontSize: 14, lineHeight: 1.6 }}>
                <b>Update (2026-07-07):</b> single sign-on via <b>OIDC is live
                today</b>, configured per workspace on Account &amp; security.
                This entry&apos;s remaining scope is SAML 2.0 federation (with
                SCIM below).
              </p>
            )}
          </section>
        ))}
      </div>

      <p style={{ marginTop: 24 }}>
        <Link className="chip" href="/login">← Back to sign in</Link>
      </p>
    </main>
  );
}
