"use client";
import { useCallback, useEffect, useState } from "react";
import { useDossier } from "@/components/dossier/DossierContext";
import { dossierApi } from "@/lib/dossierApi";
import { Term } from "@/components/Term";
import { withIntegrityManifest } from "@/lib/csvIntegrity";
// Round-9 (operations, n=4): claims → evidence. The Validation & trust panel
// is linked prominently from this page (and the isolation expander).
import { ValidationTrustPanel } from "@/components/portfolio/ValidationTrustPanel";
// Round-9 (operations MAJOR, n=15): re-launchable 'Start here' guided tour.
import { StartHereTour } from "@/components/portfolio/StartHereTour";

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
  // Round-9 (operations MAJOR, n=3): date-range + category filters on the
  // audit-trail export — not only a flat CSV.
  const [expFrom, setExpFrom] = useState("");
  const [expTo, setExpTo] = useState("");
  const [expCat, setExpCat] = useState("all");

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

  async function exportCsv() {
    if (!events?.length) return;
    const esc = (s: unknown) =>
      `"${String(s ?? "").replace(/"/g, '""')}"`;
    // Round-9 (n=3): apply the optional date-range + category export filters
    // (dates compared on the event's UTC day).
    const exportEvents = events.filter((e) => {
      if (expCat !== "all" && e.category !== expCat) return false;
      const day = e.at.slice(0, 10);
      if (expFrom && day < expFrom) return false;
      if (expTo && day > expTo) return false;
      return true;
    });
    if (!exportEvents.length) return;
    const rows = [
      ["seq", "at", "category", "action", "actor", "dossier_id", "detail"],
      ...exportEvents.map((e) => [
        e.seq, e.at, e.category, e.action,
        (e.detail?.actor as string) || "", e.dossier_id,
        JSON.stringify(
          Object.fromEntries(
            Object.entries(e.detail || {}).filter(([k]) => k !== "actor"))),
      ]),
    ];
    // Round-9 (n=5): the export is a documented inspection artifact — a
    // versioned schema line, an all-UTC statement, and an embedded SHA-256
    // manifest so any post-export edit is detectable.
    const csv = await withIntegrityManifest(
      rows.map((r) => r.map(esc).join(",")).join("\n"),
      "ands.audit-export", "1");
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
      {/* Round-9 (operations, n=4): the guarantees above, backed by the HOW —
          enforcement mechanisms, validation evidence, and the honest
          not-yet-attested list. */}
      <div style={{ margin: "10px 0" }}>
        <ValidationTrustPanel />
      </div>
      {/* Round-9 (operations MAJOR, n=15): the guided tour's last stop */}
      <StartHereTour page="audit" />
      <div className="affordance-bar" style={{ flexWrap: "wrap",
        alignItems: "baseline" }}>
        <button onClick={load}>Refresh</button>
        <button className="ghost" onClick={exportCsv}
          disabled={!events?.length}>
          Export audit report (CSV)
        </button>
        {/* Round-9 (operations MAJOR, n=3): date-range + category filters on
            the audit-trail export. */}
        <details style={{ fontSize: 12 }}>
          <summary className="mut" style={{ cursor: "pointer" }}>
            Export filters (date range · category)
          </summary>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
            alignItems: "center", marginTop: 6 }}>
            <label style={{ margin: 0 }}>From{" "}
              <input type="date" value={expFrom} style={{ width: "auto" }}
                onChange={(e) => setExpFrom(e.target.value)} />
            </label>
            <label style={{ margin: 0 }}>to{" "}
              <input type="date" value={expTo} style={{ width: "auto" }}
                onChange={(e) => setExpTo(e.target.value)} />
            </label>
            <label style={{ margin: 0 }}>Category{" "}
              <select value={expCat} style={{ width: "auto" }}
                onChange={(e) => setExpCat(e.target.value)}>
                <option value="all">all</option>
                {Array.from(new Set((events || []).map((e) => e.category)))
                  .sort()
                  .map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
              </select>
            </label>
          </div>
        </details>
        {/* Round-9 (operations MAJOR, n=5): official-record status of the
            export, stated in-app beside the button. */}
        <span className="mut" style={{ fontSize: 11.5, flexBasis: "100%" }}>
          The export is a hash-manifested <b>convenience copy</b> (all
          timestamps UTC) — this append-only server-side ledger remains the
          official inspection record.
        </span>
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
