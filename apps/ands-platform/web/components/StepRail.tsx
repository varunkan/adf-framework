"use client";
import type { Stage } from "@/lib/types";
import { Lock, Compass, Unlock } from "lucide-react";

// The gated journey rail — one current step, prior done & revisitable, later
// locked with a plain-language reason. Progressive disclosure (JRNY-REQ-001).
//
// WS-JOURNEY (round-8 MAJOR, n=8): non-linear expert filers felt "boxed in" by
// the hard linear gate. An "Expert mode" toggle turns later steps from
// HARD-locked (unclickable) into "not-yet-recommended" — dimmed but navigable —
// keeping the same plain-language reason as a non-blocking warning tooltip. The
// guided path stays the default so juniors are still walked through in order.
//
// Styling stays inline here (this workstream owns only its own components, not
// globals.css). Inline styles also let a soft-locked <li> override the
// .step.locked { cursor:not-allowed; opacity:.5 } class rule so it reads as
// navigable rather than a dead barrier.
export function StepRail({
  stages,
  activeKey,
  onSelect,
  expert,
  onExpertChange,
}: {
  stages: Stage[];
  activeKey: string;
  onSelect: (key: string) => void;
  // Expert mode: when true, locked steps are reachable (a soft warning, not a
  // barrier). Defaults to off (guided) when the props are omitted.
  expert?: boolean;
  onExpertChange?: (next: boolean) => void;
}) {
  return (
    <nav className="rail" aria-label="Filing journey">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
          margin: "0 0 14px",
        }}
      >
        <h2 style={{ margin: 0 }}>Your filing journey</h2>
        {onExpertChange && (
          <button
            type="button"
            className={`ghost${expert ? " on" : ""}`}
            role="switch"
            aria-checked={expert}
            style={{
              fontSize: 11,
              padding: "2px 9px",
              marginLeft: "auto",
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              borderRadius: 999,
            }}
            title={
              expert
                ? "Expert mode on — every step is navigable; not-yet-recommended steps show a warning but never block you."
                : "Guided mode — steps unlock in order. Turn on Expert mode to revisit or jump ahead to any step."
            }
            onClick={() => onExpertChange(!expert)}
          >
            {expert ? <Unlock size={12} aria-hidden /> : <Compass size={12} aria-hidden />}
            {expert ? "Expert mode" : "Guided mode"}
          </button>
        )}
      </div>
      {expert && (
        <p
          className="mut"
          style={{ fontSize: 11, margin: "-8px 0 12px", lineHeight: 1.4 }}
        >
          Expert mode: later steps are navigable but marked{" "}
          <b>not yet recommended</b> — the guided order is still the safe path.
        </p>
      )}
      <ol className="steps">
        {stages.map((s) => {
          // In expert mode a locked step is navigable ("not-yet-recommended");
          // in guided mode it stays a hard barrier.
          const softLocked = s.locked && !!expert;
          const selectable = !s.locked || softLocked;
          const cls = [
            "step",
            s.status,
            s.key === activeKey ? "active-sel" : "",
          ].join(" ");
          // The plain-language reason: a hard barrier when locked in guided
          // mode; a non-blocking "why it's not yet recommended" warning in
          // expert mode.
          const lockedTitle = s.gate
            ? softLocked
              ? `Not yet recommended — ${s.gate.reason} You can open it anyway in Expert mode.`
              : s.gate.reason
            : s.purpose;
          return (
            <li
              key={s.key}
              className={cls}
              role={selectable ? "button" : undefined}
              aria-disabled={selectable ? undefined : true}
              aria-current={s.current ? "step" : undefined}
              tabIndex={selectable ? 0 : -1}
              // soft-locked: override .step.locked's not-allowed/opacity so it
              // reads as navigable, not dead.
              style={
                softLocked
                  ? { cursor: "pointer", opacity: 0.74, position: "relative" }
                  : s.locked
                  ? { position: "relative" }
                  : undefined
              }
              onClick={() => selectable && onSelect(s.key)}
              onKeyDown={(e) => {
                if (selectable && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  onSelect(s.key);
                }
              }}
              title={s.locked ? lockedTitle : s.purpose}
            >
              <span className="stepdot" aria-hidden>
                {s.done ? "✓" : softLocked ? "◔" : s.locked ? "🔒" : s.icon}
              </span>
              <span>
                <span className="lbl">{s.label}</span>
                <br />
                <span
                  className="sub"
                  style={softLocked ? { color: "#e7c778" } : undefined}
                >
                  {s.done
                    ? "Done"
                    : s.current
                    ? "You're here"
                    : softLocked ? (
                        <>
                          <span aria-hidden>⚠ </span>
                          Not yet recommended{s.gate ? ` — ${s.gate.reason}` : ""}
                        </>
                      )
                    : s.gate
                    ? s.gate.reason
                    : s.reg || "Locked"}
                </span>
              </span>
              {s.locked && !softLocked && (
                <Lock
                  size={12}
                  aria-hidden
                  style={{
                    position: "absolute",
                    top: 9,
                    right: 9,
                    opacity: 0.55,
                  }}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
