"use client";
// Round-9 (operations MAJOR, n=3): "give me a cross-sponsor 'all dossiers,
// all deadlines' roll-up that survives the scope filter." This card is ALWAYS
// computed from every dossier in the workspace — it does not change when the
// Client / sponsor scope above is narrowed — with per-client percent
// complete, blocked count and next deadline, plus its own CSV export.
import { useMemo } from "react";
import type { DossierListItem } from "@/lib/dossierTypes";
import type { DossierTaskSummary } from "@/lib/collabApi";
import { withIntegrityManifest } from "@/lib/csvIntegrity";
import { dueMeta } from "@/lib/deadline";

type Row = {
  client: string;
  dossiers: number;
  ready: number;
  blocked: number;      // not ready to file (module gate outstanding)
  taskBlocked: number;  // collaboration-blocked (open task past due)
  pct: number;          // mean module completion % across the client's dossiers
  nextDue: string | null;
};

function pctOf(d: DossierListItem): number {
  const applicable = d.tower.filter((t) => t.state !== "na");
  const total = applicable.reduce((s, t) => s + (t.required_total || 0), 0);
  const filled = applicable.reduce((s, t) => s + (t.required_filled || 0), 0);
  if (!total) return d.gate?.complete ? 100 : 0;
  return Math.round((filled / total) * 100);
}

export function SponsorRollup({ items, collab }: {
  items: DossierListItem[];
  collab: Record<string, DossierTaskSummary>;
}) {
  const rows = useMemo<Row[]>(() => {
    const m = new Map<string, DossierListItem[]>();
    for (const d of items) {
      const s = (d.sponsor || "").trim() || "Unassigned";
      const list = m.get(s) || [];
      list.push(d);
      m.set(s, list);
    }
    return Array.from(m.entries())
      .map(([client, ds]) => {
        const ready = ds.filter((d) => d.gate?.complete).length;
        const dues = ds.map((d) => d.soonest_due).filter(Boolean) as string[];
        return {
          client,
          dossiers: ds.length,
          ready,
          blocked: ds.length - ready,
          taskBlocked: ds.filter((d) => collab[d.dossier_id]?.blocked).length,
          pct: Math.round(
            ds.reduce((s, d) => s + pctOf(d), 0) / (ds.length || 1)),
          nextDue: dues.length ? dues.sort()[0] : null,
        };
      })
      .sort((a, b) => a.client.localeCompare(b.client));
  }, [items, collab]);

  async function exportRollup() {
    const esc = (s: unknown) => `"${String(s ?? "").replace(/"/g, '""')}"`;
    const out = [
      ["client", "dossiers", "percent_complete", "ready_to_file",
       "blocked", "task_blocked", "next_deadline"],
      ...rows.map((r) => [r.client, r.dossiers, r.pct, r.ready, r.blocked,
                          r.taskBlocked, r.nextDue || ""]),
    ];
    const csv = await withIntegrityManifest(
      out.map((r) => r.map(esc).join(",")).join("\n"),
      "ands.sponsor-rollup", "1");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "sponsor-rollup.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // one sponsor bucket = the roll-up would duplicate the summary cards
  if (rows.length < 2) return null;

  return (
    <section className="card glass" aria-label="All-sponsors roll-up"
      style={{ marginTop: 20, padding: "16px 18px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
        flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>
          All sponsors — cross-portfolio roll-up
        </h2>
        <span className="mut" style={{ fontSize: 11.5 }}>
          always the whole workspace — unaffected by the scope filter above
        </span>
        <span style={{ marginLeft: "auto" }} />
        <button className="ghost" style={{ fontSize: 12 }}
          onClick={exportRollup}>
          Export roll-up (CSV)
        </button>
      </div>
      <ul style={{ listStyle: "none", margin: "10px 0 0", padding: 0,
        display: "grid", gap: 6, fontSize: 12.5 }}>
        {rows.map((r) => {
          const dm = dueMeta(r.nextDue);
          return (
            <li key={r.client} style={{ display: "flex", gap: 12,
              flexWrap: "wrap", alignItems: "baseline",
              borderBottom: "1px solid var(--line)", padding: "4px 2px" }}>
              <b style={{ minWidth: 140 }}>{r.client}</b>
              <span className="mut">{r.dossiers} dossier{r.dossiers === 1 ? "" : "s"}</span>
              <span title="Mean required-document completion across this client's applicable modules">
                {r.pct}% complete
              </span>
              <span className={`chip ${r.blocked ? "blocked" : "ready"}`}
                style={{ fontSize: 10.5 }}
                title={`${r.ready} ready to file · ${r.blocked} with modules outstanding` +
                  (r.taskBlocked ? ` · ${r.taskBlocked} blocked by an overdue task` : "")}>
                {r.blocked
                  ? `${r.blocked} blocked${r.taskBlocked ? ` (${r.taskBlocked} task)` : ""}`
                  : "all ready"}
              </span>
              {r.nextDue ? (
                <span className={`chip ${dm && (dm.overdue || dm.days <= 7) ? "blocked" : ""}`}
                  style={{ fontSize: 10.5 }}
                  title="This client's soonest content-plan deadline">
                  next due {r.nextDue}{dm ? ` (${dm.label})` : ""}
                </span>
              ) : (
                <span className="mut" style={{ fontSize: 11 }}>no deadline set</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
