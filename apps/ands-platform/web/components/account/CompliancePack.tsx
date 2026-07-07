"use client";
// onboarding — downloadable compliance documentation pack (n=5). Round-9
// item 9 (MAJOR): residency/compliance claims were on-screen copy only — a
// buyer needs something they can SEND to a client's compliance group. This
// builds a dated, print-styled pack (browser "Save as PDF" — stated honestly)
// with three parts:
//   (a) data-processing & residency statement — self-hosted posture plus the
//       instance-specific region indicator (declared by the operator at build
//       time via NEXT_PUBLIC_INSTANCE_REGION, or an honest "not declared");
//   (b) the 21 CFR Part 11 / GxP ALIGNMENT statement — reproduced VERBATIM
//       from the Audit & compliance card (alignment, NOT a certification);
//   (c) a validation-package summary describing only what verifiably exists,
//       and stating explicitly that IQ/OQ/PQ documentation is roadmap.
import { useEffect, useState } from "react";
import { auth, type Principal } from "@/lib/auth";

// Build-time instance declaration (inlined by Next.js). Unset ⇒ we say so.
const INSTANCE_REGION = process.env.NEXT_PUBLIC_INSTANCE_REGION || "";

function esc(s: string): string {
  return String(s ?? "").replace(/[&<>]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] || c));
}

// (b) — kept byte-identical to the on-screen statement on the Audit &
// compliance card (SecurityCompliance.tsx). DO-NOT-BREAK: alignment wording,
// "explicitly not a certification".
const PART11_STATEMENT =
  "21 CFR Part 11 / GxP alignment. Security-relevant actions land on an " +
  "append-only, actor- and workspace-stamped audit trail (below), access is " +
  "governed by role-based capabilities enforced at the API, and stored " +
  "records carry integrity metadata. This aligns with the audit-trail and " +
  "access-control expectations of 21 CFR Part 11 and GxP. Being honest: " +
  "this is an alignment statement, not a certification, and validated " +
  "cryptographically-bound e-signatures are on the roadmap — do not treat " +
  "this as a completed Part-11 e-signature system.";

function exportCompliancePack(me: Principal | null) {
  const now = new Date().toLocaleString();
  const residency = INSTANCE_REGION
    ? `This instance is hosted in <b>${esc(INSTANCE_REGION)}</b> — a region ` +
      `declared by the operator of this deployment at build time.`
    : `No hosting region has been declared for this deployment. ANDS Studio ` +
      `is self-hosted: it runs and stores data in whatever environment the ` +
      `operator deployed it to — ask your operator where this instance runs.`;

  const doc = `<!doctype html><html><head><meta charset="utf-8"/>
    <title>ANDS Studio — Compliance documentation pack</title>
    <style>
      body{font:13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#111;
        margin:32px;}
      h1{font-size:18px;margin:0 0 4px;} h2{font-size:14px;margin:22px 0 6px;}
      .mut{color:#555;} ul{margin:6px 0;padding-left:20px;}
      .foot{margin-top:24px;font-size:11px;color:#555;}
      blockquote{margin:8px 0;padding:8px 12px;border-left:3px solid #999;
        background:#f6f6f6;font-size:12px;}
    </style></head><body>
    <h1>ANDS Studio — Compliance documentation pack</h1>
    <div class="mut">Generated ${esc(now)} · workspace:
      <b>${esc(me?.tenant_name || "—")}</b> · exported by
      <b>${esc(me?.email || "—")}</b></div>

    <h2>1 · Data processing &amp; residency statement</h2>
    <p>ANDS Studio is a <b>self-hosted</b> product: every service and database
      runs inside the deploying organisation's own environment. Nothing leaves
      that environment except packages a user deliberately transmits to Health
      Canada. Because hosting is operator-controlled, data CAN be kept
      resident in Canada by deploying in a Canadian environment.</p>
    <p>${residency}</p>
    <p>Workspace isolation: every record is stamped with its workspace id and
      every service refuses cross-workspace reads at the API. One workspace =
      one client company; a workspace holds that company's dossiers, and each
      dossier holds its eCTD sequences (0000, 0001, …) — nothing in another
      workspace can reference them.</p>

    <h2>2 · 21 CFR Part 11 / GxP alignment statement</h2>
    <p class="mut">As stated in-product on the Account &amp; security page:</p>
    <blockquote>${esc(PART11_STATEMENT)}</blockquote>

    <h2>3 · Validation-package summary</h2>
    <p>What verifiably exists in this deployment today:</p>
    <ul>
      <li>a live validation rule catalogue synced to Health Canada's published
        validation criteria, run in-app against each sequence;</li>
      <li>a shadow-run parity affordance for comparing in-app validation
        results against an external run;</li>
      <li>a user-attested eValidator handoff — the app records the user's own
        attestation of the external eValidator result, it does not run
        eValidator itself.</li>
    </ul>
    <p><b>Not included:</b> formal IQ/OQ/PQ validation documentation is on the
      roadmap and is NOT part of this pack — do not present this summary as a
      completed vendor validation package.</p>

    <div class="foot">This pack is a dated browser print export ("Save as
      PDF") for sending to a client's compliance group — not a
      cryptographically signed document.</div>
    </body></html>`;

  const w = window.open("", "_blank");
  if (!w) return;
  w.document.open();
  w.document.write(doc);
  w.document.close();
  w.focus();
  setTimeout(() => { try { w.print(); } catch { /* manual print ok */ } }, 300);
}

export function CompliancePack() {
  const [me, setMe] = useState<Principal | null>(null);

  useEffect(() => {
    auth.me().then(setMe).catch(() => {});
  }, []);

  return (
    <section className="card glass" style={{ padding: "20px 22px",
      maxWidth: 760 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
        flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Compliance documentation</h2>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button className="ghost" style={{ fontSize: 12 }}
          onClick={() => exportCompliancePack(me)}>
          Download compliance documentation pack (PDF)
        </button>
      </div>
      <p className="mut" style={{ marginTop: 12, fontSize: 13 }}>
        A dated pack you can send to a client&apos;s compliance group: the
        data-processing &amp; residency statement (including this instance&apos;s
        declared hosting region{INSTANCE_REGION ? "" :
          " — none is declared for this deployment, and the pack says so"}),
        the 21 CFR Part 11 / GxP alignment statement exactly as stated
        in-product (an alignment statement, not a certification), and a
        validation-package summary that lists only what verifiably exists —
        IQ/OQ/PQ documentation is roadmap and is explicitly not included.
      </p>
    </section>
  );
}
