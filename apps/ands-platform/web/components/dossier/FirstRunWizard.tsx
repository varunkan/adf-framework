"use client";
// Round-9 builder_forms MAJOR "No guided onboarding for first-time /
// paper-native users" (n=6; quality_director_newcomer, qa_manager,
// labelling_specialist, veteran_contractor): a dismissible first-run
// walkthrough of one section end-to-end — pick → add → review → confirm —
// so a newcomer does not need a senior beside them, plus a PRINTABLE written
// quick-start procedure for SOP-binder users. It auto-opens once per browser
// (page.tsx owns that flag) and is replayable from the rail's
// "Quick-start guide" chip. A card, not a modal — it never blocks work.
//
// HONESTY BAR: every step describes only affordances that actually exist in
// the builder, and the eValidator / advisory-only caveats are repeated
// verbatim — the walkthrough must not launder them away.
import { useState } from "react";
import { BookOpen, Printer, X } from "lucide-react";
import { openPrintWindow } from "./printView";

interface Step {
  title: string;
  body: React.ReactNode;
  // the same content as plain written-procedure lines for the printout
  print: string[];
}

const STEPS: Step[] = [
  {
    title: "Pick a section (left column)",
    body: (
      <>
        The tree on the left lists every section Health Canada expects for this
        submission type. The status key above it shows what each icon means;{" "}
        <b>Required</b> sections gate filing, <b>Optional</b> ones can be
        marked N/A with a reason when they don&apos;t apply. Click a section to
        open it here in the centre.
      </>
    ),
    print: [
      "In the left column, pick the section to work on. Required sections gate filing; optional sections can be marked N/A with a written reason.",
      "The status key above the tree explains each status icon (empty / partial / complete / needs review / N/A).",
    ],
  },
  {
    title: "Add the document",
    body: (
      <>
        Use <b>Upload</b> for a finished PDF (bilingual sections have separate
        EN + FR drop zones), <b>Fill the form</b> to author in-app, or{" "}
        <b>Draft with AI</b> where the ✦ marker allows it. Greyed{" "}
        <i>&quot;example — replace this&quot;</i> values are placeholders: they
        must be replaced with your own content and block filing until cleared.
      </>
    ),
    print: [
      "Add the document: Upload a finished PDF (bilingual sections take EN and FR separately), Fill the form in-app, or Draft with AI where offered.",
      "Replace every greyed \"example — replace this\" value with your own content — unreplaced examples block filing and export.",
    ],
  },
  {
    title: "Review what you added",
    body: (
      <>
        Read the <b>&quot;What Health Canada needs here&quot;</b> box, then run
        the content review. Each finding cites the Health Canada guidance it
        derives from. A green result means{" "}
        <b>no obvious gaps found — advisory only</b>: it is a
        content-completeness check, not a screening clearance.
      </>
    ),
    print: [
      "Review: read the \"What Health Canada needs here\" guidance box and run the content review. Findings cite the HC guidance they derive from.",
      "A green review result is advisory only (content completeness) — it is NOT a screening clearance or regulatory acceptance.",
    ],
  },
  {
    title: "Confirm, then watch the gate",
    body: (
      <>
        Confirm the section as <b>your own content</b> — the confirmation is
        recorded to the Part-11 audit trail, and AI-assisted documents keep
        their provenance label permanently. The <b>Ready to transmit</b> card
        (right column) tracks Documents · Fee · Structural check. The
        structural check is not Health Canada&apos;s official eValidator — run
        eValidator before you transmit.
      </>
    ),
    print: [
      "Confirm the section as your own content. The confirmation is recorded to the Part-11 audit trail; AI-assisted documents stay labelled through review, export and audit.",
      "Track readiness on the \"Ready to transmit\" card: Documents, Fee, Structural check.",
      "The structural check is not Health Canada's official eValidator — run eValidator before you transmit.",
    ],
  },
];

function printQuickStart() {
  const steps = STEPS.map(
    (s, i) =>
      `<h2>${i + 1}. ${s.title}</h2><ul>${s.print
        .map((l) => `<li>${l}</li>`)
        .join("")}</ul>`
  ).join("");
  openPrintWindow(
    "ANDS Studio — Module builder quick-start (SOP insert)",
    `<h1>Module builder quick-start — written procedure</h1>
<div class="mut">ANDS Studio · printable SOP-binder insert · printed ${new Date()
      .toISOString()
      .slice(0, 10)}</div>
${steps}
<h2>Standing caveats</h2>
<ul>
<li>The structural check is not Health Canada's official eValidator — run eValidator before you transmit.</li>
<li>Content-review results are advisory only — a content-completeness check, never a screening clearance.</li>
<li>md5 checksums are document control, not validation.</li>
</ul>`
  );
}

export function FirstRunWizard({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [i, setI] = useState(0);
  if (!open) return null;
  const step = STEPS[i];
  return (
    <div
      className="card glass"
      role="region"
      aria-label="Quick-start guide"
      style={{ marginBottom: 16 }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <BookOpen size={15} aria-hidden style={{ alignSelf: "center" }} />
        <h3 style={{ margin: 0, fontSize: 14 }}>
          Quick start — one section, end to end
        </h3>
        <span className="mut" style={{ fontSize: 11 }}>
          step {i + 1} of {STEPS.length}
        </span>
        <button
          className="ghost"
          style={{ marginLeft: "auto", fontSize: 11, padding: "2px 8px" }}
          onClick={onClose}
          aria-label="Dismiss the quick-start guide"
        >
          <X size={12} aria-hidden /> Dismiss
        </button>
      </div>
      <div style={{ fontSize: 12.5, marginTop: 8, lineHeight: 1.55 }}>
        <b>
          {i + 1}. {step.title}
        </b>
        <div style={{ marginTop: 4 }}>{step.body}</div>
      </div>
      <div
        style={{
          display: "flex",
          gap: 8,
          marginTop: 10,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <button
          className="ghost"
          style={{ fontSize: 12, padding: "4px 10px" }}
          onClick={() => setI((v) => Math.max(0, v - 1))}
          disabled={i === 0}
        >
          ← Back
        </button>
        {i < STEPS.length - 1 ? (
          <button
            style={{ fontSize: 12, padding: "4px 12px" }}
            onClick={() => setI((v) => Math.min(STEPS.length - 1, v + 1))}
          >
            Next →
          </button>
        ) : (
          <button style={{ fontSize: 12, padding: "4px 12px" }} onClick={onClose}>
            Done — start filing
          </button>
        )}
        <button
          className="chip"
          style={{ marginLeft: "auto", fontSize: 11 }}
          onClick={printQuickStart}
          title="Print this walkthrough as a written step-by-step procedure for your SOP binder"
        >
          <Printer size={12} aria-hidden style={{ marginRight: 4, verticalAlign: "-2px" }} />
          Print the quick-start procedure
        </button>
      </div>
    </div>
  );
}
