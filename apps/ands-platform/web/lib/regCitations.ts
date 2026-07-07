// Round-6 B (TRUST): a SINGLE honest source of truth for every hard regulatory
// value shown on the face of the app — the deficiency-response windows, the
// Company-ID / Dossier-ID lead times, and the Module-4 conditional note. Each
// carries the NAME of a real Health Canada guidance (never a fabricated
// document number) and one shared "last verified against HC guidance" date so
// dates are never scattered or invented in component copy.
//
// HONESTY BAR: where the exact guidance title/number is not pinned here, the
// source is cited GENERICALLY ("Health Canada eCTD validation criteria /
// guidance") rather than inventing a specific document. Update LAST_VERIFIED
// (and the individual `verified` where it legitimately differs) when the
// underlying guidance is re-checked.

// One shared re-verification stamp for the whole regulatory-claim surface.
export const LAST_VERIFIED = "2026-07-03";

export interface RegCitation {
  // the plain regulatory value/claim being sourced
  claim: string;
  // the NAME of the real HC guidance it comes from (generic if not pinned)
  source: string;
  // "last verified against HC guidance" stamp (ISO date)
  verified: string;
  // an optional canada.ca guidance URL, when a stable one is known
  url?: string;
}

// Deficiency-response windows (SDN 45-day, NOD/NON). These are statutory /
// guidance windows, not tool behaviour.
export const DEFICIENCY_WINDOWS: Record<"SDN" | "NOD" | "NON", RegCitation> = {
  SDN: {
    claim:
      "Screening Deficiency Notice — respond by filing a response sequence " +
      "within 45 calendar days.",
    source:
      "Health Canada — Guidance: Management of Drug Submissions and " +
      "Applications (screening / deficiency handling)",
    verified: LAST_VERIFIED,
    url: "https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions.html",
  },
  NOD: {
    claim:
      "Notice of Deficiency — respond within 90 days (45 days for a DIN " +
      "application).",
    source:
      "Health Canada — Guidance: Management of Drug Submissions and " +
      "Applications (Notice of Deficiency policy)",
    verified: LAST_VERIFIED,
    url: "https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions.html",
  },
  NON: {
    claim:
      "Notice of Non-compliance — respond in the second review cycle " +
      "(45 / 90 days per the notice).",
    source:
      "Health Canada — Guidance: Management of Drug Submissions and " +
      "Applications (Notice of Non-compliance policy)",
    verified: LAST_VERIFIED,
    url: "https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions.html",
  },
};

// Pre-filing identity lead times (the prerequisites a PM must start early).
export const IDENTITY_LEAD_TIMES: Record<"companyId" | "dossierId", RegCitation> = {
  companyId: {
    claim:
      "5-digit Company ID — enrol via the Office of Submissions and " +
      "Intellectual Property; typically issued within ~2 weeks. Required " +
      "before you can transmit.",
    source:
      "Health Canada — Company & Dossier identifier enrolment (OSIP), " +
      "Regulatory Enrolment Process (REP) guidance",
    verified: LAST_VERIFIED,
    url: "https://www.canada.ca/en/health-canada/services/drug-health-product-review-approval/regulatory-enrolment-process.html",
  },
  dossierId: {
    claim:
      "Permanent Dossier ID — requested via the Regulatory Enrolment " +
      "Process (REP). Request it at most 8 weeks before you file (a maximum " +
      "lead time, not a deadline).",
    source:
      "Health Canada — Regulatory Enrolment Process (REP) guidance " +
      "(Dossier ID request)",
    verified: LAST_VERIFIED,
    url: "https://www.canada.ca/en/health-canada/services/drug-health-product-review-approval/regulatory-enrolment-process.html",
  },
};

// The Module-4 note — QUALIFIED as pathway-conditional, NOT a flat rule. A
// generic ANDS on the comparative-BE / biowaiver pathway does not need Module 4
// nonclinical animal studies; but the exception must be stated (some ANDS
// pathways can still require nonclinical data).
export const MODULE_4_NOTE: RegCitation & { conditional: string; exception: string } = {
  claim:
    "Module 4 (nonclinical / animal studies) is generally not required for a " +
    "generic ANDS.",
  conditional:
    "This is pathway-conditional, not a flat rule: it applies when eligibility " +
    "rests on comparative bioequivalence (or a justified biowaiver) against " +
    "the Canadian Reference Product.",
  exception:
    "Exception: an ANDS that cannot rely on comparative BE/biowaiver alone " +
    "(e.g. a new impurity, excipient or safety question raised by the change) " +
    "can still require nonclinical data — confirm against the specific ANDS " +
    "guidance for your product.",
  source:
    "Health Canada — Guidance Document: Comparative Bioavailability Standards " +
    "and ANDS content requirements",
  verified: LAST_VERIFIED,
  url: "https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents.html",
};

// A small inline citation string builder — keeps every "(source; last verified
// <date>)" footnote worded identically across surfaces.
export function citeLine(c: RegCitation): string {
  return `Source: ${c.source}. Last verified against HC guidance: ${c.verified}.`;
}
