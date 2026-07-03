"use client";
import { useState } from "react";
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
  const [showBreakdown, setShowBreakdown] = useState(false);
  const doneCount = data.tiles.filter((t) => t.state === "pass").length;
  return (
    <div className="card glass ready-card">
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h2>Readiness</h2>
        <span className={`ready-status ${data.status}`} style={{ marginLeft: "auto" }}>
          {data.status === "READY" ? "● READY TO FILE" : "● BLOCKED"}
        </span>
      </div>
      <div className="mut" style={{ fontSize: 12 }}>
        {data.percent}% ready — {data.done} of {data.total} filing steps complete
      </div>
      <div className="progress" aria-hidden>
        <i style={{ width: `${data.percent}%` }} />
      </div>

      <button
        className="ghost"
        style={{ fontSize: 11, padding: "2px 6px", marginTop: 6 }}
        aria-expanded={showBreakdown}
        onClick={() => setShowBreakdown((s) => !s)}
      >
        {showBreakdown
          ? "Hide breakdown"
          : `How is ${data.percent}% measured?`}
      </button>
      {showBreakdown && (
        <div style={{ marginTop: 6, fontSize: 11 }}>
          <div className="mut">
            The percentage counts completed filing steps: {doneCount} of{" "}
            {data.tiles.length} tracked steps below are done. Each step maps to
            the regulatory requirement it satisfies.
          </div>
          <ul style={{ margin: "6px 0 0 0", padding: 0, listStyle: "none" }}>
            {data.tiles.map((t) => (
              <li
                key={t.key}
                style={{
                  display: "flex",
                  gap: 6,
                  alignItems: "baseline",
                  marginTop: 4,
                }}
              >
                <span aria-hidden>{MARK[t.state] ?? "○"}</span>
                <span className="sr-only">
                  {WORD[t.state] ?? "to do"}:{" "}
                </span>
                <span style={{ fontWeight: 600 }}>{t.label}</span>
                {t.reg ? (
                  <span className="mut">— {t.reg}</span>
                ) : (
                  <span className="mut">— orientation</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

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
