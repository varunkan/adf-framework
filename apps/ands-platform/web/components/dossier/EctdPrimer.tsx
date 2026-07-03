"use client";
// Round-6 C (CLARITY) — a compact, collapsible eCTD primer/glossary explaining
// the format vocabulary professionals found unexplained: leaf, sequence,
// working vs active (0000/0001), and the new/replace/append/delete lifecycle
// operators. Reused on the draft, validate/export and journey surfaces. Detail
// stays behind a quiet <details> so the primary surface reads clean (R6-A
// progressive disclosure).
import { Term } from "../Term";

export function EctdPrimer({ compact = false }: { compact?: boolean }) {
  return (
    <details className="teach" style={{ fontSize: 13, marginTop: compact ? 6 : 10 }}>
      <summary style={{ cursor: "pointer" }}>
        <b>eCTD in plain language</b> — leaf, sequence, working vs active,
        new/replace/append/delete
      </summary>
      <ul style={{ margin: "8px 0 0", paddingLeft: 18, display: "grid", gap: 4 }}>
        <li>
          A <Term k="leaf" /> is one document at its exact place in the eCTD
          folder tree — the smallest thing the submission tracks.
        </li>
        <li>
          A <Term k="sequence" /> is one numbered package in the dossier&apos;s
          life: <code>0000</code> is the original filing, <code>0001</code>+ are
          responses and changes.
        </li>
        <li>
          The <Term k="working sequence" /> is the one you are still building
          (new documents land here); an <Term k="active sequence" /> has already
          been transmitted and is part of the official record.
        </li>
        <li>
          Each leaf carries a <Term k="lifecycle operation" />:{" "}
          <b>new</b> (first filed), <b>replace</b> (supersedes an earlier
          document), <b>append</b> (adds alongside it) or <b>delete</b>{" "}
          (withdraws it). The app writes the backbone XML that records this.
        </li>
      </ul>
    </details>
  );
}
