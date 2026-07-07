"use client";
// ROUND9-VALIDATE item 7 (n=8, "I'd probably need a senior to walk me through
// my first export"): the optional, dismissible FIRST-RUN TOUR of the
// validate/export flow. Steps once through completeness check → findings →
// sequences & lifecycle operators → export block + typed-reason override →
// eValidator handoff. Auto-opens once per browser (localStorage), skippable at
// any point, replayable from the help icon on the validation card header.
//
// HONESTY: the copy names where each element LIVES and what it does — it
// never claims the structural check is Health Canada's eValidator, and the
// final step restates the required external eValidator + CESG WebTrader path.
import { useEffect, useState } from "react";
import { AUTO_PLACEMENT_STATEMENT } from "./validationExtras";

const SEEN_KEY = "ands.tour.validate.v1";

const STEPS: { title: string; body: string }[] = [
  {
    title: "1 · The completeness check",
    body:
      "This card runs ANDS Studio's structural completeness check over the " +
      "assembled dossier — presence, format, naming, lifecycle and backbone " +
      "rules (CA-E/CA-W ids). " +
      AUTO_PLACEMENT_STATEMENT +
      " It is structural only — NOT Health Canada's official eValidator.",
  },
  {
    title: "2 · Findings",
    body:
      "Each finding row shows the rule id, its severity chip (error blocks " +
      "export; warning/advisory do not), the failing leaf, a plain message, " +
      "a one-line how-to-fix hint, and a 'Fix this' link straight to the " +
      "module page that owns the failing document. Errors are never " +
      "truncated — every blocker is on this card.",
  },
  {
    title: "3 · Sequences & lifecycle operators",
    body:
      "The Sequences panel lists each eCTD sequence with its purpose and " +
      "lifecycle-operator chips ('2× new', '1× replace'…) — 'working: NNNN' " +
      "is where new placements land. The chip legend there explains every " +
      "badge in plain language.",
  },
  {
    title: "4 · Export block & override",
    body:
      "Export fails CLOSED: if the completeness check finds errors, the " +
      "package is refused and the blocking findings are shown. You can " +
      "override only by typing a reason, which is recorded to the audit " +
      "trail — real regulatory control, not decoration.",
  },
  {
    title: "5 · eValidator handoff",
    body:
      "A clean result here is NOT a filing pass. You must still run Health " +
      "Canada's official eValidator (or your publisher's validator) on the " +
      "exported package, resolve any findings, then upload through CESG " +
      "WebTrader. The 'Path to filing' checklist on the export screen walks " +
      "each step, marking what ANDS Studio covers vs what stays external.",
  },
];

export function ValidationTour({
  open,
  onClose,
}: {
  // controlled: the parent (ValidationCard) owns the replay button
  open: boolean;
  onClose: () => void;
}) {
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (open) setStep(0);
  }, [open]);

  if (!open) return null;
  const last = step === STEPS.length - 1;
  const s = STEPS[step];

  function dismiss() {
    try {
      localStorage.setItem(SEEN_KEY, "1");
    } catch {}
    onClose();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="First-run walkthrough — validation and export"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
      onClick={dismiss}
    >
      <div
        className="card glass"
        style={{ maxWidth: 460, width: "100%", padding: 18 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>{s.title}</h3>
          <span className="mut" style={{ marginLeft: "auto", fontSize: 11 }}>
            {step + 1} / {STEPS.length}
          </span>
        </div>
        <p className="mut" style={{ fontSize: 12.5, lineHeight: 1.6, marginTop: 8 }}>
          {s.body}
        </p>
        <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
          <button
            className="ghost"
            style={{ fontSize: 12, padding: "5px 10px" }}
            onClick={dismiss}
          >
            Skip tour
          </button>
          <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            {step > 0 && (
              <button
                className="ghost"
                style={{ fontSize: 12, padding: "5px 10px" }}
                onClick={() => setStep((n) => Math.max(0, n - 1))}
              >
                Back
              </button>
            )}
            <button
              style={{ fontSize: 12, padding: "5px 12px" }}
              onClick={() => (last ? dismiss() : setStep((n) => n + 1))}
            >
              {last ? "Done" : "Next"}
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}

// One-time auto-open hook: true exactly once per browser (until the tour is
// dismissed), false after. The parent mounts <ValidationTour> with it.
export function useFirstRunTour(): [boolean, () => void, () => void] {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    try {
      if (!localStorage.getItem(SEEN_KEY)) setOpen(true);
    } catch {}
  }, []);
  return [open, () => setOpen(true), () => setOpen(false)];
}
