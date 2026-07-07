"use client";
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
  if (!def) return <>{children ?? k}</>;
  return (
    <span className="term" tabIndex={0} role="note" aria-label={`${k}: ${def}`}>
      {children ?? k}
      <span className="term-pop" aria-hidden>
        <b>{k}</b> — {def}
      </span>
    </span>
  );
}
