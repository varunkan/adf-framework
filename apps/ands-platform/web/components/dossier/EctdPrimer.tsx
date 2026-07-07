"use client";
// Round-6 C (CLARITY) — a compact, collapsible eCTD primer/glossary explaining
// the format vocabulary professionals found unexplained: leaf, sequence,
// working vs active (0000/0001), and the new/replace/append/delete lifecycle
// operators. Reused on the draft, validate/export and journey surfaces. Detail
// stays behind a quiet <details> so the primary surface reads clean (R6-A
// progressive disclosure).
//
// Round-8 WS-BUILDER (MAJOR, MAJOR wants real eCTD, not eye-candy): the primer
// now points to where the *real* backbone/XML and leaf hrefs can actually be
// inspected — the Application Viewer — so the plain-language glossary is a door
// to the substance, not a replacement for it.
import Link from "next/link";
import { FileSearch } from "lucide-react";
import { Term } from "../Term";

export function EctdPrimer({
  compact = false,
  dossierId,
}: {
  compact?: boolean;
  // when provided, the primer links straight to this dossier's Application
  // Viewer, where the real index.xml / ca-regional.xml backbone and every
  // leaf's href + checksum can be inspected.
  dossierId?: string;
}) {
  return (
    <details className="teach" style={{ fontSize: 13, marginTop: compact ? 6 : 10 }}>
      <summary style={{ cursor: "pointer" }}>
        <b>eCTD in plain language</b> — leaf, sequence, working vs active,
        new/replace/append/delete
      </summary>
      <ul style={{ margin: "8px 0 0", paddingLeft: 18, display: "grid", gap: 4 }}>
        <li>
          A <Term k="leaf" /> is one document at its exact place in the eCTD
          folder tree — the smallest thing the submission tracks. Each leaf has
          a <b>leaf id</b> and an <b>href</b> (its real path inside the
          package), both written into the backbone XML.
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
        {/* Round-9 builder_forms MAJOR "Remaining jargon undefined
            (md5/fingerprint, backbone, provenance)" (n=5): the last plain-words
            gaps, in the same voice as leaf and sequence. The hover glossary
            (lib/terms.ts) carries the same definitions; the primer spells them
            out for readers who never hover. */}
        <li>
          The <Term k="backbone" /> is the pair of XML index files —{" "}
          <code>index.xml</code> plus the Canadian <code>ca-regional.xml</code>{" "}
          — listing every leaf, its place, its checksum and its lifecycle
          operation. Health Canada&apos;s systems read the backbone, not your
          folder names.
        </li>
        <li>
          An <Term k="md5" /> (fingerprint) is a short code computed from a
          file&apos;s exact bytes — if the file changes at all, the fingerprint
          changes. It is used for <b>document control</b> (spotting silent
          changes), <b>not validation</b> or acceptance.
        </li>
        <li>
          The <Term k="provenance chip" /> on a saved document records how it
          was made — uploaded, generated from a form, or AI-assisted — and the
          label is permanent through review, export and audit.
        </li>
        <li>
          A <Term k="module badge" /> shows whether that module&apos;s required
          documents are placed — a completeness signal only; validation is a
          separate, explicit step.
        </li>
      </ul>
      {/* MAJOR: the primer is a door to the real backbone/XML, not a substitute
          for it — link to the Application Viewer where index.xml /
          ca-regional.xml and every leaf href + checksum can be inspected. */}
      {dossierId && (
        <div style={{ marginTop: 10 }}>
          <Link
            href={`/dossiers/${encodeURIComponent(dossierId)}/viewer`}
            className="chip"
            title="Open the read-only Application Viewer: the real index.xml / ca-regional.xml backbone and every leaf at its href, with checksums."
          >
            <FileSearch size={13} aria-hidden style={{ marginRight: 4, verticalAlign: "-2px" }} />
            Inspect the real backbone &amp; XML — Application Viewer
          </Link>
        </div>
      )}
    </details>
  );
}
