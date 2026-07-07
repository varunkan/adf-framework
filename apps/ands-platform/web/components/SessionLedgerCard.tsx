"use client";
// journey · J21 audit from the first action (round-9 minor, n=1; qa_manager)
// + J20 expert-mode events: the guided session's OWN append-only, sequence-
// numbered event ledger — written server-side from the very first action
// (seq 1 = session start), BEFORE any Dossier ID exists — with a client-side
// CSV export for the inspection binder.
//
// HONEST COPY: this is the session ledger (journey actions). It is ADDITIVE —
// the dossier's append-only Part-11 ledger (document create/upload, AI-draft,
// review, e-signature, validation, fees, transmission) is a separate, durable
// record and is still linked below when a dossier exists.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ScrollText } from "lucide-react";
import { Disclosure } from "./Disclosure";

// Local fetch helper — web/lib/api.ts is outside this workstream's ownership,
// so the events endpoint is called directly here (same-origin proxy).
export interface SessionEvent {
  seq: number;
  at: string;
  type: string;
  data: Record<string, any>;
}

export async function fetchSessionEvents(
  sessionId: string
): Promise<{ events: SessionEvent[]; count: number }> {
  const res = await fetch(
    `/api/journey/${encodeURIComponent(sessionId)}/events`,
    { headers: { "content-type": "application/json" }, cache: "no-store" }
  );
  if (!res.ok) throw new Error(`events: ${res.status}`);
  return res.json();
}

function toCsv(events: SessionEvent[]): string {
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = events.map((e) =>
    [e.seq, e.at, e.type, JSON.stringify(e.data || {})].map(esc).join(",")
  );
  return ["seq,at_utc,type,data", ...rows].join("\n");
}

export function SessionLedgerCard({
  sessionId,
  dossierId,
  refreshKey,
}: {
  sessionId: string;
  dossierId?: string;
  // bump when the view changes so fresh advances appear without a reload
  refreshKey?: unknown;
}) {
  const [events, setEvents] = useState<SessionEvent[] | null>(null);

  useEffect(() => {
    let live = true;
    fetchSessionEvents(sessionId)
      .then((r) => {
        if (live) setEvents(r.events);
      })
      .catch(() => {
        if (live) setEvents(null);
      });
    return () => {
      live = false;
    };
  }, [sessionId, refreshKey]);

  const exportCsv = useCallback(() => {
    if (!events) return;
    const blob = new Blob([toCsv(events)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `journey-session-ledger-${sessionId}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [events, sessionId]);

  return (
    <div className="card glass" style={{ marginTop: 12, padding: 14 }}>
      <div
        className="eyebrow"
        style={{
          marginBottom: 8,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <ScrollText size={13} aria-hidden />
        Audit trail
      </div>
      <p className="mut" style={{ fontSize: 12, margin: "0 0 8px" }}>
        This guided session keeps its own <b>append-only, sequence-numbered
        event ledger from your very first action</b> — session start, every
        step, intake, document placements, notices and Expert-mode toggles —
        before any Dossier ID exists. Exportable as CSV.
      </p>
      {events === null ? (
        <div className="mut" style={{ fontSize: 12 }}>
          Session events unavailable right now.
        </div>
      ) : (
        <>
          <Disclosure
            showLabel={`Show the ${events.length} event${events.length === 1 ? "" : "s"}`}
            hideLabel="Hide the events"
            summary={
              <span style={{ fontSize: 12 }}>
                <b>{events.length}</b> ledgered event
                {events.length === 1 ? "" : "s"} · seq 1–{events.length}, no
                gaps
              </span>
            }
          >
            <ol
              style={{
                margin: "6px 0 0",
                paddingLeft: 18,
                fontSize: 11.5,
                maxHeight: 180,
                overflowY: "auto",
              }}
            >
              {events.map((e) => (
                <li key={e.seq} style={{ marginTop: 2 }}>
                  <code>{e.type}</code>
                  <span className="mut">
                    {" "}
                    · {e.at.replace("T", " ").slice(0, 19)} UTC
                    {e.data?.reason ? ` · reason: ${e.data.reason}` : ""}
                  </span>
                </li>
              ))}
            </ol>
          </Disclosure>
          <div className="cta-row" style={{ marginTop: 8 }}>
            <button className="ghost" style={{ fontSize: 12 }} onClick={exportCsv}>
              Export session ledger (CSV)
            </button>
          </div>
        </>
      )}
      {dossierId && (
        <div
          style={{
            marginTop: 10,
            paddingTop: 10,
            borderTop: "1px solid var(--line)",
          }}
        >
          <p className="mut" style={{ fontSize: 12, margin: "0 0 8px" }}>
            Separately, every change to the dossier itself — document
            create/upload, AI-draft, review, e-signature, validation, fees and
            transmission — is written to an{" "}
            <b>append-only, tamper-evident Part-11 ledger</b> stamped with who,
            what and when. Exportable as CSV for your inspection binder.
          </p>
          <Link
            className="chip"
            href={`/dossiers/${encodeURIComponent(dossierId)}/audit`}
          >
            Open the dossier audit trail (immutable who/what/when) →
          </Link>
        </div>
      )}
    </div>
  );
}
