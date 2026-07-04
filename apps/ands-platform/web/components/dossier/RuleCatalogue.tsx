"use client";
// Round-6 A/B — the queryable rule registry, reachable directly from the
// validation FACE (not only buried on the Help page). Every CA-E/CA-W id with
// its family, severity and plain description, grouped by family, live from the
// engine (GET /validation/rules) so it can never drift from what actually runs.
import { useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { ValidationRule, ValidationCriteria } from "@/lib/dossierTypes";

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
    <div style={{ fontSize: 12 }}>
      <div className="mut" style={{ fontSize: 11 }}>
        The complete list of structural rules this checker applies
        {rules ? ` (${rules.length} rules, live from the engine)` : ""}. A rule
        id like <code>CA-E-1001</code> is an error (blocks the completeness
        gate); <code>CA-W-…</code> is an advisory warning.
      </div>
      {criteria && (
        <div className="mut" style={{ fontSize: 11, marginTop: 4 }}>
          Profile: <b>{criteria.name} v{criteria.version}</b>
          {criteria.synced ? ` · synced ${criteria.synced}` : ""}. Modeled on:{" "}
          {criteria.modeled_on}
        </div>
      )}
      {err && <div className="notice bad" style={{ marginTop: 6 }}>{err}</div>}
      {rules === null && !err && (
        <div className="mut" style={{ marginTop: 6 }}>Loading…</div>
      )}
      {rules &&
        group(rules).map(([fam, rs]) => (
          <details key={fam} style={{ marginTop: 8 }}>
            <summary style={{ cursor: "pointer" }}>
              {fam} — {rs.length} rule{rs.length === 1 ? "" : "s"}
            </summary>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {rs.map((r) => (
                <li key={r.rule_id} style={{ margin: "5px 0" }}>
                  <code>{r.rule_id}</code>
                  {r.severity === "warning" ? " (warning)" : ""} — {r.description}
                  {r.source && (
                    <div className="mut" style={{ fontSize: 10, marginTop: 1 }}>
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
