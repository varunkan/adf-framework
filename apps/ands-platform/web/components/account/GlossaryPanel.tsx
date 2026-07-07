"use client";
// onboarding — printable plain-language glossary (n=3). Round-9 item 10
// (MAJOR): "stop burying definitions behind hovers — give me a plain glossary
// or an info panel I can read and print." This is an inline, READABLE card
// (not hover-only) with one-line plain definitions for every term the
// onboarding/account surfaces lean on, plus the undefined acronyms the panel
// named (CRO, 21 CFR Part 11 — including what it does and does NOT cover —
// and GxP). "Print this glossary" opens a clean print-styled document
// (browser "Save as PDF") — same honest print-window pattern as the security
// export. Component-local copy: the hover Term popovers elsewhere are a
// different, shared surface and are left untouched.
import { useState } from "react";

const GLOSSARY: Array<{ term: string; def: string }> = [
  { term: "Workspace",
    def: "One isolated client company and its dossiers. Nothing in one " +
      "workspace can see or reference another." },
  { term: "CRO",
    def: "Contract Research Organisation — a firm that prepares and files " +
      "submissions on behalf of client (sponsor) companies." },
  { term: "MFA",
    def: "Multi-factor authentication — a second proof at sign-in (a code " +
      "from your phone) in addition to your password." },
  { term: "TOTP",
    def: "Time-based one-time password — the rotating 6-digit code an " +
      "authenticator app generates; each code lasts 30 seconds." },
  { term: "SSO",
    def: "Single sign-on — signing in through your organisation's own login " +
      "system (e.g. Okta, Microsoft Entra) instead of a separate password." },
  { term: "OIDC",
    def: "OpenID Connect — the modern open standard this product uses for " +
      "SSO sign-in." },
  { term: "SAML",
    def: "An older enterprise SSO standard. Not supported here yet — it is " +
      "on the roadmap, not available today." },
  { term: "SCIM",
    def: "Automated user provisioning — your IT systems add/remove accounts " +
      "here automatically when staff join or leave. Roadmap, not available " +
      "today." },
  { term: "SIEM",
    def: "Security Information and Event Management — your security team's " +
      "central monitoring system. Streaming this app's logs to it is " +
      "roadmap, not available today." },
  { term: "21 CFR Part 11",
    def: "The US FDA rule for electronic records and electronic signatures. " +
      "It covers audit trails, access control and signature binding for " +
      "e-records; it does NOT certify software — a product can align with " +
      "its expectations, but 'Part 11 certified' is not a thing any vendor " +
      "can honestly claim." },
  { term: "GxP",
    def: "Umbrella term for 'good practice' quality rules in regulated life " +
      "sciences (GMP, GLP, GCP…) — the compliance context this audit trail " +
      "and access control are designed for." },
  { term: "Audit trail",
    def: "The append-only, sequence-numbered record of every change — who " +
      "did what, when. Nothing in it can be silently edited or deleted." },
  { term: "E-signature",
    def: "An electronic sign-off recorded with the signer's identity and " +
      "time. Here it re-verifies your credentials at the moment of signing." },
  { term: "Dossier / sequence",
    def: "A dossier is one product's submission file; each filing round " +
      "inside it is a numbered eCTD sequence (0000, 0001, …)." },
];

function esc(s: string): string {
  return String(s ?? "").replace(/[&<>]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] || c));
}

function printGlossary() {
  const now = new Date().toLocaleString();
  const rows = GLOSSARY.map((g) =>
    `<tr><td><b>${esc(g.term)}</b></td><td>${esc(g.def)}</td></tr>`).join("");
  const doc = `<!doctype html><html><head><meta charset="utf-8"/>
    <title>ANDS Studio — Plain-language glossary</title>
    <style>
      body{font:13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#111;
        margin:32px;}
      h1{font-size:18px;margin:0 0 4px;} .mut{color:#555;}
      table{border-collapse:collapse;width:100%;margin-top:10px;}
      td{border:1px solid #bbb;padding:6px 8px;vertical-align:top;
        font-size:12px;}
      .foot{margin-top:20px;font-size:11px;color:#555;}
    </style></head><body>
    <h1>ANDS Studio — Plain-language glossary</h1>
    <div class="mut">Printable reference · generated ${esc(now)}</div>
    <table><tbody>${rows}</tbody></table>
    <div class="foot">This document is a browser print export for an SOP
      binder or desk reference — not a cryptographically signed record.</div>
    </body></html>`;
  const w = window.open("", "_blank");
  if (!w) return;
  w.document.open();
  w.document.write(doc);
  w.document.close();
  w.focus();
  setTimeout(() => { try { w.print(); } catch { /* manual print ok */ } }, 300);
}

export function GlossaryPanel() {
  const [open, setOpen] = useState(false);
  return (
    <section className="card glass" style={{ padding: "20px 22px",
      maxWidth: 760 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
        flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Plain-language glossary</h2>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button className="ghost" style={{ fontSize: 12 }}
          onClick={printGlossary}>
          Print this glossary
        </button>
      </div>
      <p className="mut" style={{ marginTop: 10, fontSize: 13 }}>
        Every term used on the sign-in and security pages, defined in one
        readable place — no hovering required. Print it for an SOP binder or a
        colleague who prefers paper.
      </p>
      <button className="ghost" style={{ fontSize: 13, marginTop: 4 }}
        aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Hide definitions ▲" : `Show all ${GLOSSARY.length} definitions ▼`}
      </button>
      {open && (
        <dl style={{ margin: "12px 0 0", display: "grid", gap: 10,
          fontSize: 13 }}>
          {GLOSSARY.map((g) => (
            <div key={g.term}>
              <dt><b>{g.term}</b></dt>
              <dd className="mut" style={{ margin: "2px 0 0 0" }}>{g.def}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
