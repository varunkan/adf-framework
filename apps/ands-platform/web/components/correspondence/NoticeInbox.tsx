"use client";
// HC notice inbox (REQ-096) — ingest an SDN/SAL/SRL/NOD/NON/NOC: advances the
// DSTS state machine, auto-logs inbound correspondence and returns the
// response-sequence shortcut. Offers a start form when no lifecycle exists.
import { useCallback, useEffect, useState } from "react";
import {
  NOTICES,
  lifecycleApi,
  today,
  type LifecycleState,
  type NoticeResult,
} from "./api";

export function NoticeInbox({
  dossierId,
  onIngested,
}: {
  dossierId: string;
  onIngested?: () => void;
}) {
  const [state, setState] = useState<LifecycleState | null>(null);
  const [missing, setMissing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  // start form
  const [receivedDate, setReceivedDate] = useState(today());
  const [submissionType, setSubmissionType] = useState("ANDS");
  // notice form
  const [notice, setNotice] = useState("SAL");
  const [noticeDate, setNoticeDate] = useState(today());
  const [subject, setSubject] = useState("");
  const [reference, setReference] = useState("");
  const [result, setResult] = useState<NoticeResult | null>(null);

  const load = useCallback(async () => {
    setErr("");
    setLoading(true);
    setResult(null);
    try {
      setState(await lifecycleApi.state(dossierId));
      setMissing(false);
    } catch (e) {
      const status = (e as Error & { status?: number }).status;
      setState(null);
      setMissing(status === 404);
      if (status !== 404) setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);
  useEffect(() => {
    load();
  }, [load]);

  async function start() {
    setBusy(true);
    setErr("");
    try {
      setState(
        await lifecycleApi.start({
          dossier_id: dossierId,
          submission_type: submissionType,
          received_date: receivedDate,
        })
      );
      setMissing(false);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function ingest() {
    setBusy(true);
    setErr("");
    try {
      const res = await lifecycleApi.ingestNotice({
        dossier_id: dossierId,
        notice,
        date: noticeDate,
        subject,
        reference,
      });
      setResult(res);
      setState(res.state);
      setSubject("");
      setReference("");
      onIngested?.();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card glass" style={{ padding: 22 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Notice inbox</h2>
        {state && (
          <>
            <span className="chip">{state.submission_type}</span>
            <span className="chip">phase: {state.phase}</span>
            <span
              className={`chip ${
                state.status === "Approved"
                  ? "ready"
                  : state.status === "Active"
                    ? ""
                    : "blocked"
              }`}
            >
              {state.status}
              {state.decision ? ` · ${state.decision}` : ""}
            </span>
          </>
        )}
      </div>
      <p className="mut" style={{ margin: "6px 0 0", maxWidth: "70ch" }}>
        Record a notice received from Health Canada. Ingesting it advances the
        DSTS lifecycle, files it as inbound correspondence and surfaces the
        response window you are now on the clock for.
      </p>

      {err && <div className="notice bad" style={{ marginTop: 12 }}>{err}</div>}

      {loading ? (
        <div className="mut" style={{ marginTop: 14 }}>Loading lifecycle…</div>
      ) : missing ? (
        <div style={{ marginTop: 14 }}>
          <div className="notice warn">
            No lifecycle has been started for <b>{dossierId}</b>. Start it from
            the date Health Canada received the submission.
          </div>
          <div className="field-row" style={{ marginTop: 8 }}>
            <div>
              <label>Submission type</label>
              <select
                value={submissionType}
                onChange={(e) => setSubmissionType(e.target.value)}
              >
                <option value="ANDS">ANDS</option>
                <option value="NDS">NDS</option>
                <option value="DIN">DIN</option>
              </select>
            </div>
            <div>
              <label>Received by HC on</label>
              <input
                type="date"
                value={receivedDate}
                onChange={(e) => setReceivedDate(e.target.value)}
              />
            </div>
          </div>
          <div className="cta-row">
            <button onClick={start} disabled={busy}>
              {busy ? "Starting…" : "Start lifecycle"}
            </button>
          </div>
        </div>
      ) : state ? (
        <>
          <div className="field-row" style={{ marginTop: 14 }}>
            <div>
              <label>Notice</label>
              <select value={notice} onChange={(e) => setNotice(e.target.value)}>
                {NOTICES.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </div>
            <div>
              <label>Date on the notice</label>
              <input
                type="date"
                value={noticeDate}
                onChange={(e) => setNoticeDate(e.target.value)}
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
          <label>Subject (optional)</label>
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder={`${notice} received`}
          />
          <div className="cta-row">
            <button onClick={ingest} disabled={busy}>
              {busy ? "Ingesting…" : `Ingest ${notice}`}
            </button>
            <span className="nexthint">
              Screening: SAL / SDN / SRL · Review decisions: NOC / NOD / NON
            </span>
          </div>
          {result && (
            <div
              className={`notice ${
                result.response.action === "none" ? "ok" : "warn"
              }`}
              style={{ marginTop: 12 }}
            >
              <b>{result.correspondence.kind_label}</b> logged.{" "}
              {result.response.label}
              {result.response.window_days
                ? ` — ${result.response.window_days}-day window from ${
                    result.correspondence.received_at
                  }.`
                : ""}
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
