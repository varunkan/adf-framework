"use client";
// CAMP-CRITERIA-SYNC — criteria-sync transparency. A regulatory buyer's adoption
// ask: "confirm the structural validator stays synced to HC criteria versions as
// HC updates them." This surfaces the AUDITABLE proof the ruleset is maintained,
// not stale: the "last reviewed / next review" cadence and the full version
// history (what changed at each version + when it was reconciled to HC). Live
// from the engine (GET /validation/criteria-history) so it can never drift from
// the rules that actually run. Reusable — used on the validation face and Help.
import { useEffect, useState } from "react";
import { dossierApi } from "@/lib/dossierApi";
import type { CriteriaHistory } from "@/lib/dossierTypes";

export function CriteriaSyncHistory({ open = false }: { open?: boolean }) {
  const [data, setData] = useState<CriteriaHistory | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    dossierApi
      .criteriaHistory()
      .then((h) => { if (live) setData(h); })
      .catch((e) => { if (live) setErr(String(e)); });
    return () => { live = false; };
  }, []);

  if (err) {
    return <div className="notice bad" style={{ fontSize: 12 }}>{err}</div>;
  }
  if (!data) {
    return <div className="mut" style={{ fontSize: 12 }}>Loading…</div>;
  }

  const rev = data.review;
  return (
    <div style={{ fontSize: 12 }}>
      <div className="mut" style={{ fontSize: 11 }}>
        How this structural ruleset is kept current with Health Canada&apos;s
        published eCTD Validation Criteria — the maintenance trail, so you can
        audit that the rules are maintained, not stale. This tracks the ANDS
        Studio structural profile; it is <b>not</b> Health Canada&apos;s official
        eValidator.
      </div>

      {/* the last-reviewed / next-review cadence commitment */}
      <div className="card glass" style={{ padding: "10px 12px", marginTop: 8 }}>
        <div style={{ fontWeight: 600 }}>Review cadence</div>
        <div className="mut" style={{ marginTop: 2 }}>{rev.cadence}</div>
        <div style={{ display: "flex", gap: 18, marginTop: 6, flexWrap: "wrap" }}>
          <span>
            Last reviewed: <b>{rev.last_reviewed}</b>
          </span>
          <span>
            Next review: <b>{rev.next_review}</b>
          </span>
        </div>
        {rev.process && (
          <div className="mut" style={{ fontSize: 11, marginTop: 6 }}>
            {rev.process}
          </div>
        )}
      </div>

      {/* the append-only version history — what changed at each sync */}
      <div style={{ fontWeight: 600, marginTop: 12 }}>
        Criteria version history
      </div>
      <div style={{ display: "grid", gap: 8, marginTop: 6 }}>
        {data.history.map((e, i) => (
          <details
            key={e.version}
            open={open && i === 0}
            className="card glass"
            style={{ padding: "8px 12px" }}
          >
            <summary style={{ cursor: "pointer" }}>
              <b>v{e.version}</b>{" "}
              <span className="mut">
                · {e.date} · synced to {e.synced_to}
              </span>
            </summary>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {e.changes.map((c, j) => (
                <li key={j} style={{ margin: "3px 0" }}>
                  {c}
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>
    </div>
  );
}
