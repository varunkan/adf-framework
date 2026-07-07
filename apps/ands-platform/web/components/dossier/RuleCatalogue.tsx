"use client";
// Round-6 A/B — the queryable rule registry, reachable directly from the
// validation FACE (not only buried on the Help page). Every CA-E/CA-W id with
// its family, severity and plain description, grouped by family, live from the
// engine (GET /validation/rules) so it can never drift from what actually runs.
import { useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { ValidationRule, ValidationCriteria } from "@/lib/dossierTypes";
import { CriteriaSyncHistory } from "./CriteriaSyncHistory";

function group(rules: ValidationRule[]): [string, ValidationRule[]][] {
  const by: Record<string, ValidationRule[]> = {};
  for (const r of rules) (by[r.family] ||= []).push(r);
  return Object.entries(by).sort((a, b) => a[0].localeCompare(b[0]));
}

// The inline body — used both standalone and inside the ValidationCard expander.
export function RuleCatalogue({ criteria }: { criteria?: ValidationCriteria }) {
  const [rules, setRules] = useState<ValidationRule[] | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    dossierApi
      .validationRules()
      .then((c) => { if (live) setRules(c.rules); })
      .catch((e) => { if (live) setErr(String(e)); });
    return () => { live = false; };
  }, []);

  return (
    <div style={{ fontSize: 12.5 }}>
      <div className="mut" style={{ fontSize: 12, lineHeight: 1.55 }}>
        The complete list of structural rules this checker applies
        {rules ? ` (${rules.length} rules, live from the engine)` : ""}. A rule
        id like <code>CA-E-1001</code> is an error (blocks the completeness
        gate); <code>CA-W-…</code> is an advisory warning.
      </div>
      {criteria && (
        <div className="mut" style={{ fontSize: 12, marginTop: 6, lineHeight: 1.55 }}>
          Profile: <b>{criteria.name} v{criteria.version}</b>
          {criteria.synced ? ` · synced ${criteria.synced}` : ""}
          {criteria.review
            ? ` · next review ${criteria.review.next_review}`
            : ""}
          . Modeled on: {criteria.modeled_on}
        </div>
      )}

      {/* CAMP-CRITERIA-SYNC: the auditable "is the ruleset kept current?" trail —
          review cadence + append-only version history, live from the engine. */}
      <details style={{ marginTop: 6 }}>
        <summary style={{ cursor: "pointer" }}>
          How this ruleset stays synced to Health Canada&apos;s criteria
        </summary>
        <div style={{ marginTop: 6 }}>
          <CriteriaSyncHistory />
        </div>
      </details>

      {err && <div className="notice bad" style={{ marginTop: 6 }}>{err}</div>}
      {rules === null && !err && (
        <div className="mut" style={{ marginTop: 6 }}>Loading…</div>
      )}
      {rules &&
        group(rules).map(([fam, rs]) => (
          <details key={fam} style={{ marginTop: 8 }}>
            <summary style={{ cursor: "pointer" }}>
              {fam} — {rs.length} rule{rs.length === 1 ? "" : "s"}
              {/* ROUND9-VALIDATE item 5: the family's Source citation is
                  visible on the summary line WITHOUT expanding (per-rule
                  detail stays collapsed to keep the uncluttered first open). */}
              {rs[0]?.source && (
                <span
                  className="mut"
                  style={{ display: "block", fontSize: 11, marginTop: 2, fontWeight: 400 }}
                >
                  Source: {rs[0].source}
                </span>
              )}
            </summary>
            <ul style={{ margin: "8px 0 0", paddingLeft: 18, lineHeight: 1.5 }}>
              {rs.map((r) => (
                <li key={r.rule_id} style={{ margin: "7px 0" }}>
                  <code>{r.rule_id}</code>
                  {r.severity === "warning" ? " (warning)" : ""} — {r.description}
                  {r.source && (
                    <div className="mut" style={{ fontSize: 11, marginTop: 2 }}>
                      Source: {r.source}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </details>
        ))}
    </div>
  );
}
