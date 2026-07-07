"use client";
import Link from "next/link";
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
      {/* journey · J17 expert non-linear without nagging (round-9 minor, n=2;
          ra_officer_generic): the intro is neutral — every step opens in any
          order; the guided order stays available in each step's tooltip
          rather than as a visible warning label. */}
      {expert && (
        <p
          className="mut"
          style={{ fontSize: 11, margin: "-8px 0 10px", lineHeight: 1.4 }}
        >
          Expert mode: every step opens in any order. The guided order stays
          in each step&apos;s tooltip if you want it.
        </p>
      )}
      {/* journey · J17 fast path: one-click jump chips for high-volume filers.
          Bulk multi-dossier work lives in the Portfolio (linked) — this rail
          drives ONE submission; that limit is stated, not papered over. */}
      {expert && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
            margin: "0 0 12px",
          }}
          aria-label="Jump to any step"
        >
          {stages.map((s) => (
            <button
              key={s.key}
              className="ghost"
              style={{
                fontSize: 10,
                padding: "1px 7px",
                borderRadius: 999,
                fontWeight: s.key === activeKey ? 700 : 400,
              }}
              title={`Jump to ${s.label}`}
              onClick={() => onSelect(s.key)}
            >
              {s.n}·{s.label.length > 14 ? `${s.label.slice(0, 13)}…` : s.label}
            </button>
          ))}
          <Link
            className="chip"
            href="/portfolio"
            style={{ fontSize: 10, padding: "1px 7px" }}
            title="Filing several dossiers at once? The portfolio roll-up is the bulk view — this rail drives one submission."
          >
            Bulk / multi-dossier → Portfolio
          </Link>
        </div>
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
          // mode. journey · J17: in expert mode the reason lives ONLY in this
          // tooltip (neutral wording, no warning label) — experts asked for
          // non-linear work "without 'not yet recommended' nagging".
          const lockedTitle = s.gate
            ? softLocked
              ? `Open anytime in Expert mode. Guided order: ${s.gate.reason}`
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
                <span className="sub">
                  {s.done
                    ? "Done"
                    : s.current
                    ? "You're here"
                    : softLocked
                    // journey · J17: neutral label, no amber ⚠ nag — the
                    // plain-language reason stays in the tooltip above.
                    ? "Open anytime · guided order suggests later"
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
