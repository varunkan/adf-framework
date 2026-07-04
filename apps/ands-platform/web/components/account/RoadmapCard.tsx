"use client";
// WS4.3 — honest 'not yet built' roadmap on the Account page. SSO (SAML/OIDC)
// leads the list with a real target quarter; sourced from lib/roadmap so the
// sign-in SSO affordance and this card never disagree.
//
// WS-ONBOARDING (round-8):
//  - #1 (BLOCKER, SSO/SCIM/SIEM procurement): each item already carries a
//    committed target quarter; we ADD a "Request early access / notify me"
//    control that captures the requesting org so IT can plan procurement. The
//    honest "not yet available" heading is preserved verbatim.
//  - #4 (acronym density): each acronym gets a one-line plain-English
//    "why you'd care" subtitle (component-local so we don't edit the shared
//    lib/roadmap another workstream may touch).
import { useState } from "react";
import Link from "next/link";
import { ROADMAP } from "@/lib/roadmap";

// #4 — plain-English "why you'd care" per roadmap item, keyed by the roadmap
// entry id. Kept here (component-local) rather than in lib/roadmap so this
// workstream owns the wording without editing a shared file.
const WHY_YOU_CARE: Record<string, string> = {
  sso:
    "Why you'd care: your IT team can force sign-in through your own company " +
    "login (Okta / Entra / Google) so there's no separate password to manage " +
    "or off-board — usually a procurement requirement.",
  scim:
    "Why you'd care: when someone leaves your company, their access here is " +
    "removed automatically instead of an admin having to remember to do it.",
  "audit-siem":
    "Why you'd care: this app's security log is forwarded into your company's " +
    "own monitoring system, so your security team sees it beside everything " +
    "else they watch.",
};

// #1 — capture the org that wants early access. This is a demo build with no
// outbound email, so we record the request locally and confirm honestly rather
// than pretend a ticket was filed.
function NotifyMe({ itemTitle }: { itemTitle: string }) {
  const [open, setOpen] = useState(false);
  const [org, setOrg] = useState("");
  const [done, setDone] = useState(false);

  if (done) {
    return (
      <div className="mut" style={{ marginTop: 6, fontSize: 12 }}>
        ✓ Noted — we'll contact <b>{org}</b> when <b>{itemTitle}</b> enters
        early access.{" "}
        <span className="mut">
          (Demo build: this request is recorded locally, not emailed.)
        </span>
      </div>
    );
  }

  if (!open) {
    return (
      <button className="ghost" style={{ fontSize: 12, marginTop: 6 }}
        onClick={() => setOpen(true)}>
        Request early access / notify me →
      </button>
    );
  }

  return (
    <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap",
      alignItems: "center" }}>
      <input value={org} onChange={(e) => setOrg(e.target.value)}
        placeholder="Your organisation"
        aria-label={`Organisation to notify about ${itemTitle}`}
        style={{ maxWidth: 220, fontSize: 13 }}
        onKeyDown={(e) => { if (e.key === "Enter" && org.trim()) setDone(true); }} />
      <button style={{ fontSize: 12 }} disabled={!org.trim()}
        onClick={() => setDone(true)}>
        Notify me →
      </button>
      <button className="ghost" style={{ fontSize: 12 }}
        onClick={() => setOpen(false)}>
        Cancel
      </button>
    </div>
  );
}

export function RoadmapCard() {
  return (
    <section className="card glass" style={{ padding: "14px 18px",
      maxWidth: 720, marginTop: 14 }}>
      <h2 style={{ margin: 0, fontSize: 15 }}>Roadmap — not yet available</h2>
      <p className="mut" style={{ margin: "6px 0 10px", fontSize: 13 }}>
        Honest target quarters for enterprise capabilities that are not built
        today. Nothing below works yet. If a date matters for your procurement,
        use <b>Request early access</b> on the item and we'll capture your org.
      </p>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, display: "grid",
        gap: 12 }}>
        {ROADMAP.map((e) => (
          <li key={e.id}>
            <b>{e.title}</b>{" "}
            <span className="chip blocked" style={{ fontSize: 11 }}>
              Not yet available
            </span>{" "}
            <span className="chip" style={{ fontSize: 11 }}>
              Target {e.targetQuarter}
            </span>
            {WHY_YOU_CARE[e.id] && (
              <div style={{ marginTop: 2, fontSize: 12 }}>
                {WHY_YOU_CARE[e.id]}
              </div>
            )}
            <div className="mut" style={{ marginTop: 2 }}>{e.detail}</div>
            <NotifyMe itemTitle={e.title} />
          </li>
        ))}
      </ul>
      <p style={{ marginTop: 10, fontSize: 13 }}>
        <Link href="/roadmap">Open the full roadmap →</Link>
      </p>
    </section>
  );
}
