"use client";
import { TERMS } from "@/lib/terms";

// Inline jargon translation on first use: a dashed-underlined term that reveals
// its plain-language meaning on hover/focus (keyboard-accessible).
export function Term({ k, children }: { k: string; children?: React.ReactNode }) {
  const def = TERMS[k];
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
