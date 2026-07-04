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
  open: controlledOpen,
  onOpenChange,
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
  // Optional controlled open-state — lets a parent persist it (e.g. across
  // module switches). Falls back to uncontrolled when omitted.
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const controlled = controlledOpen != null;
  const open = controlled ? (controlledOpen as boolean) : uncontrolled;
  const setOpen = (next: boolean) => {
    if (!controlled) setUncontrolled(next);
    onOpenChange?.(next);
  };
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
            onClick={() => setOpen(!open)}
          >
            {open ? hideLabel : showLabel}
          </button>
        )}
      </div>
      {shown && <div className="disclosure-body">{children}</div>}
    </div>
  );
}
