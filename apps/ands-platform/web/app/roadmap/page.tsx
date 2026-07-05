// WS4.3 — public, honest roadmap. Linked from the sign-in card's SSO affordance
// (/roadmap#sso) and mirrored in the Account page Roadmap card. States target
// quarters plainly and never implies a not-yet-built capability works today.
import Link from "next/link";
import { ROADMAP } from "@/lib/roadmap";

export const metadata = { title: "Roadmap · ANDS Studio" };

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
        {ROADMAP.map((e) => (
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
          </section>
        ))}
      </div>

      <p style={{ marginTop: 24 }}>
        <Link className="chip" href="/login">← Back to sign in</Link>
      </p>
    </main>
  );
}
