// FIX-PDFA-NOISE — collapse the repetitive PDF/A-1b advisory warnings into a
// PER-RULE summary.
//
// The structural validator (services/dossier/app/ectd_validation.py) emits the
// PDF/A conformance-marker advisories — CA-W-7006 (missing XMP pdfaid packet),
// CA-W-7007 (incomplete XMP packet), CA-W-7008 (missing OutputIntent), CA-W-7009
// (PDF version > 1.4) — ONCE PER LEAF. A dossier with a dozen plain uploaded PDFs
// therefore shows 10-12 near-identical warning rows for what is really 2-4 rules.
// Filers under a deadline misread that wall of yellow as failures.
//
// This is a PURE grouping helper (no React, no I/O) so it is trivial to reason
// about and (if a web test runner is ever added) to unit-test. It does NOT touch
// the rule contract on the backend, and it is deliberately CONSERVATIVE:
//
//   - it ONLY groups WARNING findings whose rule_id is a PDF/A advisory
//     (CA-W-70xx). Hard errors (CA-E-*) never pass through here and stay
//     individually visible in the caller.
//   - any warning it does not recognise as a PDF/A advisory is returned
//     untouched in `other`, so the grouping can never HIDE a real finding.
//   - the affected leaves are preserved verbatim per group so the caller can
//     put them behind an expander — nothing is discarded.
import type { ValidationFinding } from "./dossierTypes";

// The advisory rule-id family this helper collapses. CA-W-70xx == PDF/A-1b
// conformance-marker advisories (see RULE_IDS in ectd_validation.py). Kept as a
// prefix test so a new CA-W-70xx advisory folds in automatically.
const PDFA_ADVISORY_PREFIX = "CA-W-70";

// A human, per-rule short label so the grouped headline reads as prose, not a
// bare rule id. Falls back to the finding's own `rule`/`rule_id` when unknown.
const PDFA_RULE_LABEL: Record<string, string> = {
  "CA-W-7006": "XMP metadata packet",
  "CA-W-7007": "XMP metadata packet (incomplete)",
  "CA-W-7008": "OutputIntent colour space",
  "CA-W-7009": "PDF version > 1.4",
};

export interface PdfaAdvisoryGroup {
  // the CA-W-70xx rule id shared by every finding in this group
  rule_id: string;
  // the machine rule name (e.g. "pdfa_xmp_missing"), from the first finding
  rule: string;
  // short human label for the headline
  label: string;
  // how many leaves tripped this advisory
  count: number;
  // the affected leaf ids (deduped, order-preserving). May contain "" for a
  // finding with no leaf, which we surface as "(document)".
  leaves: string[];
  // the representative message (from the first finding) — the per-leaf messages
  // differ only by the leaf name, so one is enough to explain the advisory.
  message: string;
}

export interface GroupedWarnings {
  // PDF/A advisories collapsed to one entry per rule id, ordered by rule id so
  // the summary is stable across runs.
  pdfaGroups: PdfaAdvisoryGroup[];
  // every warning that is NOT a PDF/A advisory, untouched and still individual.
  other: ValidationFinding[];
}

function isPdfaAdvisory(f: ValidationFinding): boolean {
  return typeof f.rule_id === "string" && f.rule_id.startsWith(PDFA_ADVISORY_PREFIX);
}

// Split a warning list into per-rule PDF/A advisory groups + untouched others.
// Errors must NOT be passed in — the caller keeps them individually visible.
export function groupPdfaWarnings(warnings: ValidationFinding[]): GroupedWarnings {
  const byRule = new Map<string, PdfaAdvisoryGroup>();
  const order: string[] = [];
  const other: ValidationFinding[] = [];

  for (const f of warnings) {
    if (!isPdfaAdvisory(f)) {
      other.push(f);
      continue;
    }
    const rid = f.rule_id as string;
    let g = byRule.get(rid);
    if (!g) {
      g = {
        rule_id: rid,
        rule: f.rule,
        label: PDFA_RULE_LABEL[rid] || f.rule || rid,
        count: 0,
        leaves: [],
        message: f.message,
      };
      byRule.set(rid, g);
      order.push(rid);
    }
    g.count += 1;
    const leaf = f.leaf || "";
    if (!g.leaves.includes(leaf)) g.leaves.push(leaf);
  }

  // stable ordering: by rule id ascending (CA-W-7006, 7007, 7008, 7009)
  order.sort();
  const pdfaGroups = order.map((rid) => byRule.get(rid) as PdfaAdvisoryGroup);
  return { pdfaGroups, other };
}
