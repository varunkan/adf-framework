"use client";
// HC correspondence hub (REQ-112) — every letter/notice/query exchanged with
// Health Canada for one dossier, plus a form to log a new record.
import { useCallback, useEffect, useState } from "react";
import {
  KINDS,
  lifecycleApi,
  today,
  type CorrespondenceRecord,
} from "./api";

export function CorrespondenceHub({ dossierId }: { dossierId: string }) {
  const [items, setItems] = useState<CorrespondenceRecord[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [logging, setLogging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState("letter");
  const [direction, setDirection] = useState("inbound");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [receivedAt, setReceivedAt] = useState(today());
  const [reference, setReference] = useState("");

  const load = useCallback(async () => {
    setErr("");
    setLoading(true);
    try {
      setItems(
        (await lifecycleApi.listCorrespondence(dossierId, filter)).correspondence
      );
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [dossierId, filter]);
  useEffect(() => {
    load();
  }, [load]);

  async function log() {
    setBusy(true);
    setErr("");
    try {
      await lifecycleApi.logCorrespondence({
        dossier_id: dossierId,
        kind,
        subject,
        body,
        direction,
        received_at: receivedAt,
        reference,
      });
      setSubject("");
      setBody("");
      setReference("");
      setLogging(false);
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card glass" style={{ padding: 22 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Correspondence hub</h2>
        <span className="mut" style={{ fontSize: 12 }}>
          {items.length} record{items.length === 1 ? "" : "s"}
        </span>
        <span className="spacer" style={{ marginLeft: "auto" }} />
        <select
          aria-label="Filter by kind"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ width: "auto" }}
        >
          <option value="">All kinds</option>
          {Object.entries(KINDS).map(([k, label]) => (
            <option key={k} value={k}>
              {k} — {label}
            </option>
          ))}
        </select>
        <button onClick={() => setLogging((v) => !v)}>
          {logging ? "Cancel" : "Log correspondence +"}
        </button>
      </div>
      <p className="mut" style={{ margin: "6px 0 0", maxWidth: "70ch" }}>
        Every letter, notice and query exchanged with Health Canada on this
        dossier — inbound (HC → sponsor) and outbound (sponsor → HC).
      </p>

      {logging && (
        <div className="card" style={{ marginTop: 14, padding: 16 }}>
          <div className="field-row">
            <div>
              <label>Kind</label>
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {Object.entries(KINDS).map(([k, label]) => (
                  <option key={k} value={k}>
                    {k} — {label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>Direction</label>
              <select
                value={direction}
                onChange={(e) => setDirection(e.target.value)}
              >
                <option value="inbound">Inbound (HC → sponsor)</option>
                <option value="outbound">Outbound (sponsor → HC)</option>
              </select>
            </div>
            <div>
              <label>Date</label>
              <input
                type="date"
                value={receivedAt}
                onChange={(e) => setReceivedAt(e.target.value)}
              />
            </div>
          </div>
          <div className="field-row">
            <div>
              <label>Subject</label>
              <input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="e.g. Response to clarifax on 3.2.P.8 stability"
              />
            </div>
            <div>
              <label>HC reference (optional)</label>
              <input
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="e.g. HC6-024-e123456"
              />
            </div>
          </div>
          <label>Body / summary (optional)</label>
          <textarea
            rows={3}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Key points of the letter…"
          />
          <div className="cta-row">
            <button onClick={log} disabled={busy || !subject.trim()}>
              {busy ? "Logging…" : "Log record"}
            </button>
          </div>
        </div>
      )}

      {err && <div className="notice bad" style={{ marginTop: 12 }}>{err}</div>}

      {loading ? (
        <div className="mut" style={{ marginTop: 14 }}>Loading correspondence…</div>
      ) : items.length === 0 ? (
        <div className="notice" style={{ marginTop: 14 }}>
          No correspondence on file{filter ? ` for kind ${filter}` : ""} yet.
        </div>
      ) : (
        <ul
          style={{
            listStyle: "none",
            margin: "14px 0 0",
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {items.map((c) => (
            <li
              key={c.id}
              className="card"
              style={{
                padding: "10px 14px",
                display: "flex",
                gap: 12,
                alignItems: "baseline",
                flexWrap: "wrap",
              }}
            >
              <span className="chip" title={c.kind_label}>{c.kind}</span>
              <span
                className={`chip ${c.direction === "inbound" ? "blocked" : "ready"}`}
              >
                {c.direction === "inbound" ? "HC → sponsor" : "sponsor → HC"}
              </span>
              <span style={{ fontWeight: 600 }}>{c.subject}</span>
              {c.body && (
                <span className="mut" style={{ fontSize: 13 }}>{c.body}</span>
              )}
              <span className="spacer" style={{ marginLeft: "auto" }} />
              {c.reference && (
                <span className="mut" style={{ fontSize: 12 }}>
                  ref {c.reference}
                </span>
              )}
              <span className="mut" style={{ fontSize: 12 }}>
                {c.received_at || c.created_at.slice(0, 10)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
