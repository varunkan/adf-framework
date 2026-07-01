"use client";
import type { Stage } from "@/lib/types";

// The gated journey rail — one current step, prior done & revisitable, later
// locked with a plain-language reason. Progressive disclosure (JRNY-REQ-001).
export function StepRail({
  stages,
  activeKey,
  onSelect,
}: {
  stages: Stage[];
  activeKey: string;
  onSelect: (key: string) => void;
}) {
  return (
    <nav className="rail" aria-label="Filing journey">
      <h2>Your filing journey</h2>
      <ol className="steps">
        {stages.map((s) => {
          const selectable = !s.locked;
          const cls = [
            "step",
            s.status,
            s.key === activeKey ? "active-sel" : "",
          ].join(" ");
          return (
            <li
              key={s.key}
              className={cls}
              role={selectable ? "button" : undefined}
              aria-disabled={s.locked ? true : undefined}
              aria-current={s.current ? "step" : undefined}
              tabIndex={selectable ? 0 : -1}
              onClick={() => selectable && onSelect(s.key)}
              onKeyDown={(e) => {
                if (selectable && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  onSelect(s.key);
                }
              }}
              title={s.locked && s.gate ? s.gate.reason : s.purpose}
            >
              <span className="stepdot" aria-hidden>
                {s.done ? "✓" : s.locked ? "🔒" : s.icon}
              </span>
              <span>
                <span className="lbl">{s.label}</span>
                <br />
                <span className="sub">
                  {s.done
                    ? "Done"
                    : s.current
                    ? "You're here"
                    : s.gate
                    ? s.gate.reason
                    : s.reg || "Locked"}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
