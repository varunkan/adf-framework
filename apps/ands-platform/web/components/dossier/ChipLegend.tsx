"use client";
// ROUND9-VALIDATE item 4 (n=11, "I dislike how much assumed vocabulary there
// is"): a plain-language legend for every chip TYPE the validate/export flow
// renders. Terms themselves (leaf, sequence, backbone…) already have <Term>
// tooltips + the EctdPrimer glossary; this legend explains the CHIPS — the
// colored badges whose meaning was previously assumed.
import { useState } from "react";

const GROUPS: { title: string; items: { chip: string; meaning: string }[] }[] = [
  {
    title: "Lifecycle-operator chips (per sequence)",
    items: [
      {
        chip: "2× new",
        meaning:
          "Two documents placed for the first time in this sequence — they do not touch anything transmitted before.",
      },
      {
        chip: "1× replace",
        meaning:
          "One document that supersedes a document from a PRIOR sequence — Health Canada's reviewer sees the new one as current.",
      },
      {
        chip: "1× append",
        meaning:
          "A document added alongside a prior one (both stay current) — e.g. an addendum.",
      },
      {
        chip: "1× delete",
        meaning:
          "Retires a prior document from the current view without sending a replacement.",
      },
    ],
  },
  {
    title: "Purpose chips (what a sequence is for)",
    items: [
      {
        chip: "Initial / Response / Supplement / Annual notification",
        meaning:
          "The regulatory purpose of the sequence — e.g. 'Response' answers a Health Canada screening deficiency; 'working: NNNN' names the sequence new placements currently land in.",
      },
    ],
  },
  {
    title: "Severity chips (findings)",
    items: [
      {
        chip: "error",
        meaning:
          "Blocks the completeness gate — export is refused until fixed (or explicitly overridden with a typed reason).",
      },
      {
        chip: "warning",
        meaning: "Should be reviewed, but does not block export.",
      },
      {
        chip: "advisory",
        meaning:
          "Informational only (e.g. PDF/A markers absent) — never blocks anything.",
      },
    ],
  },
  {
    title: "Status chips",
    items: [
      {
        chip: "● ACTIVE",
        meaning:
          "The working sequence — new document placements land here.",
      },
      {
        chip: "● NO STRUCTURAL ISSUES (structural; not HC eValidator)",
        meaning:
          "The structural completeness check found no blocking issues. It is NOT a Health Canada eValidator pass and NOT acceptance — that step is still yours to run.",
      },
      {
        chip: "BLOCKED / ● N issue(s)",
        meaning:
          "Blocking structural error(s) exist — export is gated until they are resolved or overridden with a typed, audited reason.",
      },
      {
        chip: "eValidator: cleared (user-attested, report attached)",
        meaning:
          "YOU attested an external eValidator PASS and attached the actual report file. ANDS Studio records it as external evidence — it never runs HC's eValidator itself.",
      },
    ],
  },
];

// A small, dismissible legend affordance — mount it next to the chips it
// explains (SequencePanel) and beside the persistent glossary (ValidationCard).
export function ChipLegend({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: compact ? 6 : 8 }}>
      <button
        className="ghost"
        style={{ fontSize: 11, padding: "2px 8px" }}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "Hide chip legend" : "Chip legend — what the badges mean"}
      </button>
      {open && (
        <div className="notice" style={{ marginTop: 6, fontSize: 11.5, lineHeight: 1.55 }}>
          {GROUPS.map((g) => (
            <div key={g.title} style={{ marginTop: 6 }}>
              <div style={{ fontWeight: 600 }}>{g.title}</div>
              <ul style={{ margin: "3px 0 0 16px", padding: 0 }}>
                {g.items.map((it) => (
                  <li key={it.chip} className="mut" style={{ marginTop: 3 }}>
                    <span className="chip" style={{ fontSize: 10, marginRight: 6 }}>
                      {it.chip}
                    </span>
                    {it.meaning}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
