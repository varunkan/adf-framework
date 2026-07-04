"use client";
import { useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import { RuleCatalogue } from "./dossier/RuleCatalogue";
import { EctdPrimer } from "./dossier/EctdPrimer";
import type { ValidationCriteria } from "@/lib/dossierTypes";
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
  const [showRules, setShowRules] = useState(false);
  // R6-B: name + version the validation profile that underpins READY-TO-FILE,
  // live from the engine so it can never drift. (Round-5 blocker: "which
  // ruleset/version underpins READY-TO-FILE?")
  const [criteria, setCriteria] = useState<ValidationCriteria | null>(null);
  useEffect(() => {
    let live = true;
    dossierApi.validationRules()
      .then((c) => { if (live) setCriteria(c.criteria); })
      .catch(() => {});
    return () => { live = false; };
  }, []);
  const doneCount = data.tiles.filter((t) => t.state === "pass").length;
  return (
    <div className="card glass ready-card">
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h2>Readiness</h2>
        <span className={`ready-status ${data.status}`} style={{ marginLeft: "auto" }}>
          {data.status === "READY" ? "● READY TO FILE" : "● BLOCKED"}
        </span>
      </div>
      {/* Tier 1 — the filing checklist (workflow completeness). */}
      <div className="mut" style={{ fontSize: 12 }}>
        <b>Filing checklist:</b> {data.done} of {data.total} steps complete (
        {data.percent}%)
      </div>
      {/* Tier 2 — the REAL, named eCTD technical validation verdict. Distinct
          from the checklist so the green badge reads as a validation pass, not a
          step-completion checkbox (round-7 #1 blocker, all 24 respondents). */}
      {(() => {
        const v = data.validation;
        const crit = v?.criteria ?? criteria;
        const prof = crit
          ? `${crit.name} v${crit.version}${crit.synced ? ` · synced ${crit.synced}` : ""}`
          : "the structural eCTD validator";
        let head: JSX.Element;
        if (!v || !v.ran) {
          head = (
            <span className="mut">
              ◻ <b>eCTD technical validation:</b> not yet run — complete the
              Validate step to run it.
            </span>
          );
        } else if (v.passed) {
          head = (
            <span style={{ color: "#128a3a" }}>
              ✓ <b>eCTD technical validation passed</b> — 0 errors
              {v.warnings ? `, ${v.warnings} warning${v.warnings === 1 ? "" : "s"}` : ""}{" "}
              across {v.checked} checks.
            </span>
          );
        } else {
          head = (
            <span style={{ color: "#c0392b" }}>
              ✗ <b>eCTD technical validation:</b> {v.errors} error
              {v.errors === 1 ? "" : "s"} must be fixed.
            </span>
          );
        }
        return (
          <div style={{ fontSize: 11, marginTop: 4 }}>
            <div>{head}</div>
            <div className="mut" style={{ marginTop: 2 }}>
              Against <b>{prof}</b> — structural/technical checks, not HC&apos;s
              official eValidator; run eValidator before you transmit.{" "}
              <button
                className="ghost"
                style={{ fontSize: 11, padding: "1px 5px" }}
                aria-expanded={showRules}
                onClick={() => setShowRules((s) => !s)}
              >
                {showRules ? "Hide rule catalogue" : "Rule catalogue"}
              </button>
            </div>
            {v && v.ran && !v.passed && v.failing_rules.length > 0 && (
              <ul style={{ margin: "4px 0 0", paddingLeft: 16 }}>
                {v.failing_rules.map((f, i) => (
                  <li key={f.rule_id + i}>
                    <code>{f.rule_id}</code> — {f.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })()}
      {showRules && (
        <div style={{ marginTop: 6 }}>
          <RuleCatalogue criteria={criteria ?? undefined} />
        </div>
      )}
      <div className="progress" aria-hidden>
        <i style={{ width: `${data.percent}%` }} />
      </div>

      <EctdPrimer compact />

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
