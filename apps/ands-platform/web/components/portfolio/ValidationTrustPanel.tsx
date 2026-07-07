"use client";
// Round-9 (operations BLOCKER, n=4): "'Part-11 record' and 'mirrored to the
// central governance trail' are claims, not evidence." One in-app
// Validation & trust panel, linked from the Audit page and the isolation
// expander, stating (a) what validation evidence exists, (b) exactly HOW
// audit-trail immutability and tamper-evidence are enforced, and (c) the
// honest status of independent attestation. HONESTY IS THE PRODUCT: what is
// not built is stated as not built — nothing here dresses up unshipped
// capability.
import { useState } from "react";
import { ShieldCheck } from "lucide-react";

export function ValidationTrustPanel({ defaultOpen = false }: {
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="card glass" style={{ padding: 0 }}>
      <button
        className="ghost"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={{ width: "100%", textAlign: "left", padding: "12px 18px",
          fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}
      >
        <ShieldCheck size={15} aria-hidden />
        Validation &amp; trust — how these guarantees are enforced
        <span className="mut" style={{ fontWeight: 400, fontSize: 12 }}>
          evidence, mechanisms, and what is NOT yet attested
        </span>
        <span style={{ marginLeft: "auto" }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div style={{ padding: "0 18px 16px", display: "grid", gap: 12,
          fontSize: 12.5, maxWidth: "84ch" }}>
          <section>
            <b>Audit-trail immutability &amp; tamper-evidence — the mechanism.</b>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "grid", gap: 3 }}>
              <li>
                The audit ledger is <b>append-only</b>: events are written by
                INSERT-only code paths and <b>no API route exists</b> to update
                or delete an audit event.
              </li>
              <li>
                Every event carries a <b>gap-detectable sequence number</b> plus
                actor, workspace and a UTC timestamp — a removed or reordered
                entry breaks the sequence visibly.
              </li>
              <li>
                CSV exports embed a <b>SHA-256 integrity manifest</b> with the
                verification procedure stated in-file, so any post-export edit
                is detectable. The server-side ledger remains the official
                record; exports are convenience copies.
              </li>
              <li>
                Controlled e-signatures (annual checklist, submission sign-off)
                require <b>credential re-verification at the moment of
                signing</b> and record a meaning-of-signature on an append-only
                signing log.
              </li>
            </ul>
          </section>
          <section>
            <b>Workspace / tenant isolation — the mechanism.</b>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "grid", gap: 3 }}>
              <li>
                Every client-data row is stamped with its workspace (tenant id)
                and every service filters by it: <b>cross-workspace reads are
                refused at the API layer</b>, not merely hidden in the UI.
              </li>
              <li>
                Guessing another workspace&apos;s record id returns 404 — the
                API never confirms that another tenant&apos;s record exists.
              </li>
            </ul>
          </section>
          <section>
            <b>Computer-system validation evidence — what exists today.</b>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "grid", gap: 3 }}>
              <li>
                Each backend service ships an <b>automated regression suite</b>
                {" "}(including dedicated tenant-isolation, e-signature and
                audit-event tests) that is run against the service before
                changes ship; the suites live in the same repository as the
                code they verify.
              </li>
              <li>
                The 21 CFR Part 11 / GxP line is worded as <b>alignment</b> —
                explicitly <b>not a certification</b>.
              </li>
            </ul>
          </section>
          <section className="notice" style={{ fontSize: 12 }}>
            <b>Not yet available — stated plainly:</b> a formal, deployment-
            specific IQ/OQ/PQ validation package you can hand to your QA unit
            is <b>not yet published</b>, and there is <b>no independent SOC 2 /
            third-party tenancy attestation</b> backing the isolation guarantee
            today. Both remain roadmap items without a committed date; until
            they exist, the enforcement mechanisms and automated-test evidence
            above are the honest extent of the validation story.
          </section>
        </div>
      )}
    </div>
  );
}
