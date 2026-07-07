"use client";
// WS3: workspace-wide audit viewer + inspection export for the Account &
// security page. Renders GET /api/governance/audit (tenant-scoped by the proxy)
// newest-first, with a Download button offering the service's PlainText export
// (GET /audit/export) plus client-built CSV / JSON of the same events.
import { useCallback, useEffect, useState } from "react";
import {
  governanceApi,
  auditToCsv,
  download,
  type AuditEvent,
} from "@/lib/governanceApi";
// onboarding — item 1 (BLOCKER n=8): the workspace CSV export becomes
// tamper-evident like the dossier audit export — same embedded SHA-256
// integrity manifest (import-only reuse of the shared helper).
import { withIntegrityManifest } from "@/lib/csvIntegrity";

function when(at: string): string {
  const d = new Date(at);
  return isNaN(d.getTime()) ? at : d.toLocaleString();
}

function compactDetail(detail: Record<string, unknown>): string {
  const parts = Object.entries(detail || {})
    .filter(([k]) => k !== "actor")
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  const s = parts.join(" · ");
  return s.length > 160 ? s.slice(0, 157) + "…" : s;
}

export function WorkspaceAudit() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError("");
    governanceApi
      .listAudit(200)
      .then(setEvents)
      .catch((e) => {
        setEvents([]);
        setError(String(e?.message || e));
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function downloadPlain() {
    setBusy(true);
    try {
      const text = await governanceApi.exportText();
      download("workspace-audit.txt", text, "text/plain");
    } catch (e) {
      setError(String(e));
    }
    setBusy(false);
  }

  async function downloadCsv() {
    if (!events?.length) return;
    // item 1 — embed the SHA-256 integrity manifest so any post-export edit
    // is detectable (verification procedure travels inside the file).
    const csv = await withIntegrityManifest(
      auditToCsv(events), "ands.workspace-audit-export", "1");
    download("workspace-audit.csv", csv, "text/csv");
  }

  function downloadJson() {
    if (!events?.length) return;
    download(
      "workspace-audit.json",
      JSON.stringify(events, null, 2),
      "application/json"
    );
  }

  return (
    <section
      className="card glass"
      style={{ padding: "20px 22px", maxWidth: 760 }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h2 style={{ margin: 0 }}>Audit trail</h2>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <button className="ghost" onClick={load} style={{ fontSize: 12 }}>
          Refresh
        </button>
      </div>
      <p className="mut" style={{ marginTop: 10, fontSize: 14 }}>
        The append-only governance record for this workspace — every domain
        event, actor- and workspace-stamped, sequence-numbered, newest first.
        Download for a regulatory inspection record.
      </p>

      <div
        className="affordance-bar"
        style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0" }}
      >
        <button className="ghost" onClick={downloadPlain} disabled={busy}>
          {busy ? "Preparing…" : "Download (inspection .txt)"}
        </button>
        <button
          className="ghost"
          onClick={downloadCsv}
          disabled={!events?.length}
        >
          Download CSV
        </button>
        <button
          className="ghost"
          onClick={downloadJson}
          disabled={!events?.length}
        >
          Download JSON
        </button>
      </div>

      {events === null ? (
        <div className="mut" style={{ fontSize: 13 }}>
          Loading audit trail…
        </div>
      ) : error ? (
        <div className="mut" style={{ fontSize: 13 }}>
          Audit trail unavailable — {error}
        </div>
      ) : events.length === 0 ? (
        <div className="mut" style={{ fontSize: 13 }}>
          No audit events recorded for this workspace yet.
        </div>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {events.map((e) => (
            <li
              key={e.id}
              style={{
                padding: "8px 2px",
                borderBottom: "1px solid var(--line)",
                display: "flex",
                gap: 10,
                alignItems: "baseline",
                flexWrap: "wrap",
                fontSize: 13,
              }}
            >
              <span className="chip" style={{ fontSize: 11 }}>
                {e.category || "unknown"}
              </span>
              <b>{e.action}</b>
              <span className="mut" style={{ fontSize: 11 }}>
                #{e.seq} · {when(e.at)}
                {e.dossier_id ? ` · ${e.dossier_id}` : ""}
              </span>
              {typeof e.detail?.actor === "string" && e.detail.actor && (
                <span className="chip" style={{ fontSize: 11 }}>
                  by {e.detail.actor as string}
                </span>
              )}
              {compactDetail(e.detail) && (
                <span
                  className="mut"
                  style={{ fontSize: 11, flexBasis: "100%" }}
                >
                  {compactDetail(e.detail)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {events !== null && !error && (
        <div className="mut" style={{ marginTop: 8, fontSize: 12 }}>
          {events.length} event{events.length === 1 ? "" : "s"} shown (latest
          200).
        </div>
      )}
    </section>
  );
}
