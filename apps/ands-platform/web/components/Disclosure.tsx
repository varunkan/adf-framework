"use client";
// Round-6 WS-A (DENSITY REDUCTION via progressive disclosure). A calm, reusable
// expander: a one-line summary with a "Show details" affordance, secondary
// detail collapsed by default. NEVER wrap a blocking/safety state in this —
// those must stay expanded and visible. Nothing is removed; the summary always
// carries a visible toggle, so every collapsed section stays reachable.
import { useState, type ReactNode } from "react";

export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  showLabel = "Show details",
  hideLabel = "Hide details",
  className,
  forceOpen = false,
  forceOpenNote,
}: {
  // one-line summary (the single primary thing this row shows when collapsed)
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  showLabel?: string;
  hideLabel?: string;
  className?: string;
  // SAFETY: when true, the section is held OPEN and cannot be collapsed — use
  // for a blocking/safety state (e.g. an active export block) that must never
  // be hidden behind a collapsed expander.
  forceOpen?: boolean;
  forceOpenNote?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const shown = open || forceOpen;
  return (
    <div className={`disclosure${className ? ` ${className}` : ""}`}>
      <div className="disclosure-head">
        <div className="disclosure-summary">{summary}</div>
        {forceOpen ? (
          forceOpenNote ? (
            <span className="mut disclosure-toggle" aria-hidden>
              {forceOpenNote}
            </span>
          ) : null
        ) : (
          <button
            type="button"
            className="ghost disclosure-toggle"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? hideLabel : showLabel}
          </button>
        )}
      </div>
      {shown && <div className="disclosure-body">{children}</div>}
    </div>
  );
}
