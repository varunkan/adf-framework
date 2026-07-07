"use client";
import { useCallback, useEffect, useState } from "react";
import { useDossier } from "@/components/dossier/DossierContext";
import { dossierApi } from "@/lib/dossierApi";
import { Term } from "@/components/Term";

type AuditEvent = {
  id: string;
  seq: number;
  at: string;
  category: string;
  action: string;
  dossier_id: string;
  tenant_id: string;
  detail: Record<string, unknown>;
};

function when(at: string): string {
  const d = new Date(at);
  return isNaN(d.getTime()) ? at : d.toLocaleString();
}

function compact(detail: Record<string, unknown>): string {
  // actor is surfaced as its own chip, so drop it from the detail line
  const parts = Object.entries(detail || {})
    .filter(([k]) => k !== "actor")
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  const s = parts.join(" · ");
  return s.length > 160 ? s.slice(0, 157) + "…" : s;
}

export default function AuditPage() {
  const { dossierId } = useDossier();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    // PRIMARY: the DURABLE dossier-local Part-11 ledger (chained across
    // renames). This is the authoritative record — it cannot silently lose an
    // entry when the governance forward is down, which the governance /audit
    // read could. Governance is no longer the source of truth for this panel.
    dossierApi
      .getHistory(dossierId)
      .then((body) =>
        setEvents(
          (body.events || []).map((e) => ({
            id: `${e.dossier_id}:${e.seq}`,
            seq: e.seq,
            at: e.timestamp,
            category: (e.event_type.split(".")[0] || "dossier"),
            action: e.event_type,
            dossier_id: e.dossier_id,
            tenant_id: e.tenant_id,
            // fold actor + reason into the detail line the renderer expects
            detail: {
              ...(e.actor ? { actor: e.actor } : {}),
              ...(e.reason ? { reason: e.reason } : {}),
              ...e.data,
            },
          }))
        )
      )
      .catch((e) => {
        setEvents([]);
        setError(String(e?.message || e));
      });
  }, [dossierId]);

  useEffect(() => {
    load();
  }, [load]);

  function exportCsv() {
    if (!events?.length) return;
    const esc = (s: unknown) =>
      `"${String(s ?? "").replace(/"/g, '""')}"`;
    const rows = [
      ["seq", "at", "category", "action", "actor", "dossier_id", "detail"],
      ...events.map((e) => [
        e.seq, e.at, e.category, e.action,
        (e.detail?.actor as string) || "", e.dossier_id,
        JSON.stringify(
          Object.fromEntries(
            Object.entries(e.detail || {}).filter(([k]) => k !== "actor"))),
      ]),
    ];
    const csv = rows.map((r) => r.map(esc).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `audit-${dossierId}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <main className="viewer">
      <p className="eyebrow">Audit · Part-11 record</p>
      <h1>Audit Trail</h1>
      <p className="lede">
        The durable, append-only <Term k="Part-11" /> record for this dossier — written
        synchronously alongside each change and preserved even if the central
        governance service is unreachable. Newest first; chained across a
        Dossier ID re-key so history for the prior ID still resolves.
      </p>
      {/* the guarantees, stated where QA looks for them */}
      <div className="notice" style={{ fontSize: 13 }}>
        Append-only, gap-detectable sequence numbers · every event stamped
        with actor and workspace · covers document creation/upload/AI-draft,
        review, e-signature, validation, fees and transmission events ·
        export below for inspection records.
      </div>
      <div className="affordance-bar">
        <button onClick={load}>Refresh</button>
        <button className="ghost" onClick={exportCsv}
          disabled={!events?.length}>
          Export audit report (CSV)
        </button>
      </div>

      <div className="card glass">
        {events === null ? (
          <div className="mut">Loading audit trail…</div>
        ) : error ? (
          <div className="mut">Audit trail unavailable — {error}</div>
        ) : events.length === 0 ? (
          <div className="mut">No audit events recorded for this dossier yet.</div>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {events.map((e) => (
              <li
                key={e.id}
                style={{
                  padding: "10px 2px",
                  borderBottom: "1px solid var(--line)",
                  display: "flex",
                  gap: 12,
                  alignItems: "baseline",
                  flexWrap: "wrap",
                }}
              >
                <span className="chip">{e.category || "unknown"}</span>
                <b>{e.action}</b>
                <span className="mut" style={{ fontSize: 12.5 }}>
                  #{e.seq} · {when(e.at)}
                </span>
                {typeof e.detail?.actor === "string" && e.detail.actor && (
                  <span className="chip" style={{ fontSize: 12 }}>
                    by {e.detail.actor as string}
                  </span>
                )}
                {compact(e.detail) && (
                  <span
                    className="mut"
                    style={{ fontSize: 12.5, flexBasis: "100%" }}
                  >
                    {compact(e.detail)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {events !== null && !error && (
          <div className="mut" style={{ marginTop: 10, fontSize: 13 }}>
            {events.length} event{events.length === 1 ? "" : "s"} · durable
            dossier-local ledger, mirrored to the central governance trail
          </div>
        )}
      </div>
    </main>
  );
}
