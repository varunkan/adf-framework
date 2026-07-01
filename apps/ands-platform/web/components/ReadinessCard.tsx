"use client";
import type { ReadinessCardData } from "@/lib/types";

const MARK: Record<string, string> = { pass: "✓", current: "◉", todo: "○" };
const WORD: Record<string, string> = {
  pass: "complete",
  current: "in progress",
  todo: "to do",
};

// The persistent READY / BLOCKED card — plain-language blockers + Resume.
export function ReadinessCard({
  data,
  onResume,
}: {
  data: ReadinessCardData;
  onResume: (key: string) => void;
}) {
  return (
    <div className="card glass ready-card">
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h2>Readiness</h2>
        <span className={`ready-status ${data.status}`} style={{ marginLeft: "auto" }}>
          {data.status === "READY" ? "● READY TO FILE" : "● BLOCKED"}
        </span>
      </div>
      <div className="mut" style={{ fontSize: 12 }}>
        {data.done} of {data.total} filing steps complete
      </div>
      <div className="progress" aria-hidden>
        <i style={{ width: `${data.percent}%` }} />
      </div>

      <div className="tiles">
        {data.tiles.map((t) => (
          <div key={t.key} className={`tile ${t.state}`} title={t.reg || t.label}>
            <span className="d" aria-hidden>{MARK[t.state] ?? "○"}</span>
            <span className="sr-only">{WORD[t.state] ?? "to do"}: </span>
            {t.label}
          </div>
        ))}
      </div>

      {data.blocking_items.length > 0 && (
        <div className="blockers">
          <div className="mut" style={{ fontSize: 12 }}>
            The single thing standing between you and ready:
          </div>
          {data.blocking_items.map((b) => (
            <div key={b.key} className="b">
              <b>{b.label}</b> — {b.requirement}
              <div style={{ marginTop: 8 }}>
                <button onClick={() => onResume(b.key)}>
                  {b.cta || "Do this next"} →
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {data.status === "READY" && (
        <div className="notice ok" style={{ marginTop: 14 }}>
          Everything checks out — your package is ready to transmit to Health
          Canada.
        </div>
      )}
    </div>
  );
}
