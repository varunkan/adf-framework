"use client";
import { useCallback, useEffect, useState } from "react";
import { lifecycleApi } from "@/lib/lifecycleApi";
import type { LifecycleState, LifecycleTimer, ServiceStandard } from "@/lib/lifecycleApi";
import { dueMeta } from "@/lib/deadline";
import { DEFICIENCY_WINDOWS, citeLine } from "@/lib/regCitations";
import { ProvenancePopover, type Provenance } from "@/components/ProvenancePopover";

// WS-OPS-PROV (Round-8 BLOCKER, n=14): the deficiency-response clock is a
// COMPUTED statutory clock too, and previously carried a citation footnote but
// no provenance popover and no "calculated aid" caveat. Build the same
// Provenance shape the NOA/RTS clocks use, straight from the lifecycle timer
// (start = the HC notice date, basis, due) and the honest DEFICIENCY_WINDOWS
// citation — nothing fabricated.
const DEFICIENCY_TITLE: Record<string, string> = {
  SDN: "Screening Deficiency Notice (SDN)",
  NOD: "Notice of Deficiency (NOD)",
  NON: "Notice of Non-compliance (NON)",
};

function deficiencyProvenance(
  kind: "SDN" | "NOD" | "NON",
  timer: LifecycleTimer,
): Provenance {
  const cite = DEFICIENCY_WINDOWS[kind];
  return {
    anchorLabel: `${DEFICIENCY_TITLE[kind]} issued by Health Canada`,
    anchorDate: timer.start ?? null,
    anchorSource: "ingested",
    basis: timer.basis === "business" ? "business" : "calendar",
    rule: cite.claim,
    citation: cite.source,
    instrument:
      "Food and Drug Regulations (C.R.C., c. 870) — as applied through HC's " +
      "Management of Drug Submissions and Applications guidance",
    derivedFrom: {
      label: `${DEFICIENCY_TITLE[kind]} recorded on the dossier`,
      date: timer.start ?? null,
      source: "ingested from the HC notice into the lifecycle service",
    },
  };
}

// WS7 — LIFECYCLE & DEFICIENCY (addresses regops_publisher "lifecycle blindness").
// Surfaces the DSTS submission lifecycle for this dossier from the lifecycle
// service: submission TYPE + its service standard (review target), the current
// phase/status, and — when the dossier sits in a screening/deficiency state
// (SDN → 45-day, NOD/NON → 90-day) — the RESPONSE PATH with its statutory clock.
// Every value is read from GET /api/lifecycle/state|service-standard; nothing is
// hardcoded. A dossier whose lifecycle has not been started reads as "not yet
// filed" (the service returns 404), never as an error.

// Which lifecycle timer represents the OPEN deficiency-response window, and the
// regulatory label + response path for it. These map the DSTS notice model
// (services/lifecycle/app/lifecycle.py + service._RESPONSE_SHORTCUTS).
const DEFICIENCY: Record<
  string,
  { title: string; path: string }
> = {
  SDN: {
    title: "Screening Deficiency Notice (SDN)",
    path: "File a response sequence within the 45-day window to keep the submission alive.",
  },
  NOD: {
    title: "Notice of Deficiency (NOD)",
    path: "File a clarifax/response within the window (90 days; 45 for DIN).",
  },
  NON: {
    title: "Notice of Non-compliance (NON)",
    path: "File a response sequence within the window.",
  },
};

function statusTone(status: string): string {
  if (status.startsWith("Inactive")) return "blocked";
  if (status === "Approved") return "ready";
  if (status === "Screening-Rejected" || status === "Withdrawn") return "blocked";
  return "";
}

export function LifecyclePanel({ dossierId }: { dossierId: string }) {
  const [state, setState] = useState<LifecycleState | null>(null);
  const [std, setStd] = useState<ServiceStandard | null>(null);
  const [notStarted, setNotStarted] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const s = await lifecycleApi.state(dossierId);
      setState(s);
      setNotStarted(false);
      setError("");
      try {
        setStd(await lifecycleApi.serviceStandard(s.submission_type));
      } catch {
        setStd(null);
      }
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 404) {
        setNotStarted(true);
        setState(null);
        setError("");
      } else {
        setError(String((e as Error).message || e));
      }
    }
  }, [dossierId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // The open deficiency timer (SDN/NOD/NON) whose response clock is running.
  const defKind = state
    ? (state.decision && DEFICIENCY[state.decision] && state.status.startsWith("Inactive")
        ? state.decision
        : state.screening_outcome === "SDN" && state.status.startsWith("Inactive")
          ? "SDN"
          : "")
    : "";
  const defTimer = state?.timers.find((t) => t.kind === defKind);
  const dm = defTimer ? dueMeta(defTimer.due) : null;

  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <div className="mut" style={{ fontSize: 12 }}>
          Submission lifecycle
        </div>
        {state && (
          <span
            className={`chip ${statusTone(state.status)}`}
            style={{ marginLeft: "auto", fontSize: 11 }}
          >
            {state.phase} · {state.status}
          </span>
        )}
      </div>

      {error && (
        <div className="notice bad" style={{ marginTop: 8, fontSize: 12 }}>
          {error}
        </div>
      )}

      {notStarted && (
        <div className="mut" style={{ marginTop: 8, fontSize: 12 }}>
          No Health Canada lifecycle yet — this dossier has not been filed. The
          DSTS clock (screening, review, deficiency windows) starts once HC
          records receipt.
        </div>
      )}

      {state && (
        <div style={{ marginTop: 8, display: "grid", gap: 6, fontSize: 12 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
            <span className="chip">{state.submission_type}</span>
            {std && (
              <span className="mut">
                {std.label} · {std.review_target_days}-day review standard (
                {std.on_time_pct}% on-time)
              </span>
            )}
          </div>

          {state.review_due && (
            <div className="mut">
              Review target due {state.review_due}
              {(() => {
                const r = dueMeta(state.review_due);
                return r ? ` · ${r.label}` : "";
              })()}
            </div>
          )}

          {defKind && defTimer && (
            <div
              className="notice bad"
              style={{ fontSize: 12 }}
              role="status"
              aria-label={`${DEFICIENCY[defKind].title} response window`}
            >
              <div style={{ fontWeight: 700 }}>
                Deficiency response required — {DEFICIENCY[defKind].title}
              </div>
              <div style={{ marginTop: 3 }}>{DEFICIENCY[defKind].path}</div>
              <div style={{ marginTop: 6, display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <span
                  className={`chip ${dm && (dm.overdue || dm.days <= 7) ? "blocked" : ""}`}
                  style={{ fontSize: 11 }}
                >
                  ⏱ {defTimer.days}-day clock · due {defTimer.due}
                  {dm ? ` · ${dm.label}` : ""}
                </span>
                {/* WS-OPS-PROV: full source citation + derivation for this
                    computed clock, via the shared provenance popover. */}
                {DEFICIENCY_WINDOWS[defKind as "SDN" | "NOD" | "NON"] && (
                  <ProvenancePopover
                    prov={deficiencyProvenance(
                      defKind as "SDN" | "NOD" | "NON",
                      defTimer,
                    )}
                  />
                )}
                {/* WS-OPS-PROV: the calculated-aid caveat stamped on the clock. */}
                <span
                  className="mut"
                  style={{ fontSize: 10 }}
                  title="Calculated aid — verify against the HC record"
                >
                  · calculated aid
                </span>
                {defTimer.adjusted && (
                  <span className="mut" style={{ fontSize: 11 }}>
                    (adjusted for a statutory holiday/weekend)
                  </span>
                )}
              </div>
              {DEFICIENCY_WINDOWS[defKind as "SDN" | "NOD" | "NON"] && (
                <div className="mut" style={{ fontSize: 10, marginTop: 6 }}>
                  {citeLine(DEFICIENCY_WINDOWS[defKind as "SDN" | "NOD" | "NON"])}
                </div>
              )}
            </div>
          )}

          {state.fee_credit && (
            <div className="mut" style={{ fontSize: 11 }}>
              A 25% service-standard fee credit applies — HC decided after the
              review target.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
