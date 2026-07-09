"use client";
import { useRef, useState } from "react";
import { TERMS } from "@/lib/terms";

// R9-OVERALL "Rule-ID and eCTD jargon lacks inline plain-English explainers"
// (n=9) — the panel flagged three terms with NO entry anywhere: the invented
// product terms "Submission tower" and "Portfolio roll-up", and "PDF
// conformance". They are defined here (component-local supplement, merged
// beneath lib/terms.ts so the shared glossary always wins) so any surface can
// simply render <Term k="Submission tower"> and get the hover explainer.
const EXTRA_TERMS: Record<string, string> = {
  "Submission tower":
    "Our name for the module-by-module progress picture of one dossier — " +
    "which of Modules 1–5 are complete, blocked or empty. What it means for " +
    "you: it's the same data as the plain checklist (the default view), just " +
    "stacked visually. Nothing regulatory hangs on the word 'tower'.",
  "Portfolio roll-up":
    "Our name for the all-dossiers summary row: totals, blockers and soonest " +
    "deadlines added up across every dossier you can see. What it means for " +
    "you: one glance tells you which product needs attention today — click " +
    "through for the per-dossier detail.",
  "PDF conformance":
    "Health Canada's systems only accept PDFs with certain technical " +
    "properties (version, no passwords, embedded fonts, usable bookmarks). " +
    "What it means for you: a document can look perfect on screen and still " +
    "be rejected — the full technical check reads the stored bytes so you " +
    "find out here, not after transmitting.",
};

// Inline jargon translation on first use: a dashed-underlined term that reveals
// its plain-language meaning on hover/focus (keyboard-accessible).
export function Term({ k, children }: { k: string; children?: React.ReactNode }) {
  const def = TERMS[k] ?? EXTRA_TERMS[k];
  const ref = useRef<HTMLSpanElement>(null);
  const [flip, setFlip] = useState(false);
  if (!def) return <>{children ?? k}</>;
  // Keep the 280px popover on-screen: when the term sits near the right edge
  // (right rail, table cells), flip the popover to open leftward so its content
  // is never clipped by the viewport. Measured on hover/focus (the only time it
  // shows), so no layout cost at rest.
  const place = () => {
    const el = ref.current;
    if (!el || typeof window === "undefined") return;
    const r = el.getBoundingClientRect();
    const popW = Math.min(280, window.innerWidth - 24);
    // flip to open leftward ONLY when the popover would overflow the right edge
    // AND right-aligning keeps its left edge on-screen (otherwise stay put — never
    // trade a right-clip for a worse left-clip on a narrow viewport).
    const overflowsRight = r.left + popW > window.innerWidth - 8;
    const fitsWhenFlipped = r.right - popW >= 8;
    setFlip(overflowsRight && fitsWhenFlipped);
  };
  return (
    <span ref={ref} className={"term" + (flip ? " term-flip" : "")} tabIndex={0}
      role="note" aria-label={`${k}: ${def}`}
      onMouseEnter={place} onFocus={place}>
      {children ?? k}
      <span className="term-pop" aria-hidden>
        <b>{k}</b> — {def}
      </span>
    </span>
  );
}
