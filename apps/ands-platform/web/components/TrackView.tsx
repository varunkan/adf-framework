"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { TrackSummary } from "@/lib/types";
import { Term } from "./Term";

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

      {summary?.timers.map((t) => (
        <div key={`${t.notice.type}-${t.notice.date}`}
          className={`timer ${t.overdue ? "overdue" : ""} ${t.paused ? "paused" : ""}`}>
          <div className="timer-head">
            <span className="timer-count">
              {t.paused ? "⏸" : t.overdue ? Math.abs(t.days_remaining) : t.days_remaining}
            </span>
            <span className="timer-unit">
              {t.paused ? "paused" : t.overdue ? "days overdue" : "days left"}
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
    </div>
  );
}
