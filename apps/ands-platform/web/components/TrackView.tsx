"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { TrackSummary } from "@/lib/types";
import { citeLine, LAST_VERIFIED, type RegCitation } from "@/lib/regCitations";
import { Term } from "./Term";
import { Disclosure } from "./Disclosure";

// journey · J5 post-NOC Level I/II/III (round-9 BLOCKER, n=4; ra_director_cro,
// regops_publisher) — the citation for the change-classification framework.
const POST_NOC_FRAMEWORK: RegCitation = {
  claim:
    "Post-NOC changes are classified Level I (supplement), Level II " +
    "(Notifiable Change) or Level III (record at Annual Notification).",
  source:
    "Health Canada — Post-Notice of Compliance (NOC) Changes: Framework " +
    "guidance (with the Quality / Safety-Efficacy appendices)",
  verified: LAST_VERIFIED,
};

const NOTICES = [
  { type: "SDN", label: "Log a screening deficiency (SDN)" },
  { type: "clarifax", label: "Log a clarifax (review question)" },
  { type: "NOD", label: "Log a Notice of Deficiency (NOD)" },
  { type: "NOC", label: "Log approval (NOC)" },
];

export function TrackView({ sessionId }: { sessionId: string }) {
  const [summary, setSummary] = useState<TrackSummary | null>(null);
  const [today, setToday] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (asof: string) => {
      setSummary(await api.track(sessionId, asof));
    },
    [sessionId]
  );

  useEffect(() => {
    const t = new Date().toISOString().slice(0, 10);
    setToday(t);
    load(t).catch(() => {});
  }, [load]);

  async function logNotice(type: string) {
    setBusy(true);
    try {
      await api.logNotice(sessionId, type, today);
      await load(today);
    } finally {
      setBusy(false);
    }
  }

  async function togglePause(type: string, paused: boolean) {
    setBusy(true);
    try {
      await api.pauseClock(sessionId, type, paused);
      await load(today);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="track-view">
      {summary && (
        <div className="phase-pill">
          <span className="d" />
          {summary.phase.label}
          <em className="mut"> · {summary.phase.explanation}</em>
        </div>
      )}

      <div className="track-actions">
        <span className="mut" style={{ fontSize: 13 }}>
          Simulate a Health Canada notice to see the timers:
        </span>
        <div className="cta-row" style={{ marginTop: 8 }}>
          {NOTICES.map((n) => (
            <button key={n.type} className="ghost" disabled={busy}
              onClick={() => logNotice(n.type)}>
              {n.label}
            </button>
          ))}
        </div>
      </div>

      {summary && summary.timers.length === 0 && (
        <div className="notice" style={{ marginTop: 14 }}>
          No open deadlines. Log a notice above to start a response timer.
        </div>
      )}

      <div role="status" aria-live="polite">
      {summary?.timers.map((t, i) => (
        <div key={`${t.notice.type}-${t.notice.date}-${i}`}
          className={`timer ${t.overdue ? "overdue" : ""} ${t.paused ? "paused" : ""}`}>
          <div className="timer-head">
            <span className="timer-count">
              {t.paused
                ? "⏸"
                : t.days_remaining == null
                ? "?"
                : t.overdue
                ? Math.abs(t.days_remaining)
                : t.days_remaining}
            </span>
            <span className="timer-unit">
              {t.paused
                ? "paused"
                : t.days_remaining == null
                ? "check date"
                : t.overdue
                ? "days overdue"
                : "days left"}
            </span>
          </div>
          <div className="timer-body">
            <b>{t.label}</b>
            <div className="mut" style={{ fontSize: 13, marginTop: 4 }}>
              {t.guidance}
            </div>
            <div className="mut" style={{ fontSize: 12, marginTop: 4 }}>
              Due {t.due_date} · {t.window_days}-day window
            </div>
            {t.notice.type === "clarifax" && (
              <button className="ghost" style={{ marginTop: 8 }} disabled={busy}
                onClick={() => togglePause(t.notice.type, !t.paused)}>
                {t.paused ? "Resume the clock" : "Pause the clock"}
              </button>
            )}
          </div>
        </div>
      ))}
      </div>

      {summary?.advisories.map((a) => (
        <div key={a.rule}
          className={`notice ${a.rule === "srl_risk" ? "warn" : ""}`}
          style={{ marginTop: 12 }}>
          {a.rule === "hc_time_only" ? "⏱ " : "⚠ "}
          {a.message}
        </div>
      ))}

      <p className="mut" style={{ fontSize: 13, marginTop: 14 }}>
        A <Term k="clarifax" /> asks you to clarify data you already filed; the
        decisions are <Term k="NOC" />, <Term k="NOD" /> or <Term k="NON" />.
      </p>

      {/* journey · J5 post-NOC changes · HONEST SUBSET: plain guidance on
          HC's Level I/II/III classification + the SANDS pathway pointer.
          Studio does NOT auto-classify a change's level — that limit is
          stated flatly below, not implied away. Collapsed by default so the
          tracking view keeps its calm first-open feel. */}
      <div style={{ marginTop: 14 }}>
        <Disclosure
          showLabel="Show the change levels"
          hideLabel="Hide the change levels"
          summary={
            <span style={{ fontSize: 13 }}>
              <b>After approval — post-NOC changes (Level I / II / III).</b>{" "}
              Real ANDS work continues after the <Term k="NOC" />.
            </span>
          }
        >
          <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5,
            lineHeight: 1.55 }}>
            <li>
              <b>Level I — Supplement (prior approval).</b> Significant
              quality/labelling changes need Health Canada&apos;s approval
              BEFORE implementation — for a generic, filed as a{" "}
              <Term k="SANDS" /> (Supplement to an ANDS).
            </li>
            <li style={{ marginTop: 4 }}>
              <b>Level II — Notifiable Change.</b> Moderate changes are filed
              as a notification; you may implement per the guidance&apos;s
              conditions while HC screens it.
            </li>
            <li style={{ marginTop: 4 }}>
              <b>Level III — Annual Notification.</b> Minor changes are
              recorded and reported in your Annual Notification — no
              submission at the time of change.
            </li>
          </ul>
          <div className="notice warn" style={{ marginTop: 8, fontSize: 12 }}>
            Honest limit: ANDS Studio does <b>not</b> auto-classify your
            change&apos;s level — classify it yourself against the guidance&apos;s
            appendices, and when in doubt treat it as the higher level.
          </div>
          <div className="cta-row" style={{ marginTop: 8 }}>
            <Link className="chip" href="/dossiers">
              File a Level I change: SANDS — Supplement to an ANDS →
            </Link>
          </div>
          <p className="mut" style={{ fontSize: 10.5, margin: "8px 0 0" }}>
            {citeLine(POST_NOC_FRAMEWORK)}
          </p>
        </Disclosure>
      </div>
    </div>
  );
}
