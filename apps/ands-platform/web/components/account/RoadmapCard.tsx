"use client";
// WS4.3 — honest 'not yet built' roadmap on the Account page. SSO (SAML/OIDC)
// leads the list with a real target quarter; sourced from lib/roadmap so the
// sign-in SSO affordance and this card never disagree.
import Link from "next/link";
import { ROADMAP } from "@/lib/roadmap";

export function RoadmapCard() {
  return (
    <section className="card glass" style={{ padding: "14px 18px",
      maxWidth: 720, marginTop: 14 }}>
      <h2 style={{ margin: 0, fontSize: 15 }}>Roadmap — not yet available</h2>
      <p className="mut" style={{ margin: "6px 0 10px", fontSize: 13 }}>
        Honest target quarters for enterprise capabilities that are not built
        today. Nothing below works yet.
      </p>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, display: "grid",
        gap: 8 }}>
        {ROADMAP.map((e) => (
          <li key={e.id}>
            <b>{e.title}</b>{" "}
            <span className="chip" style={{ fontSize: 11 }}>
              Target {e.targetQuarter}
            </span>
            <div className="mut" style={{ marginTop: 2 }}>{e.detail}</div>
          </li>
        ))}
      </ul>
      <p style={{ marginTop: 10, fontSize: 13 }}>
        <Link href="/roadmap">Open the full roadmap →</Link>
      </p>
    </section>
  );
}
