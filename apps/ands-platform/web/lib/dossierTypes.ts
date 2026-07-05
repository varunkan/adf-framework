// Shapes from the dossier microservice (apps/ands-platform/services/dossier).
import type { ModuleTower } from "./types";

export type Applicability = "required" | "optional" | "suppressed" | "na";
export type SectionStatus = "empty" | "partial" | "complete" | "na";
export type Affordance = "upload" | "generate" | "mark_na";

export interface DocMeta {
  doc_id: string;
  dossier_id?: string;
  section?: string;
  filename: string;
  content_type: string;
  checksum: string;
  size: number;
  origin: "uploaded" | "generated" | "ai_draft";
  lang?: string | null;
}

export interface SectionNode {
  id: string;
  module: string;
  section: string;
  title: string;
  kind: "group" | "document";
  depth: number;
  applicability: Applicability;
  affordances: Affordance[];
  generator_key: string | null;
  ai_draftable?: boolean;
  formats: string[];
  bilingual: boolean;
  purpose: string;
  guidance: string;
  source_url: string;
  folder: string;
  leaf_id: string;
  // live per-dossier state
  status: SectionStatus;
  action?: "uploaded" | "generated" | "na" | null;
  document?: DocMeta | null;
  documents?: Record<string, DocMeta> | null;
  languages?: string[] | null;
  na_reason?: string | null;
  // WS2 safety provenance: how the section's content was produced and whether
  // the filer has confirmed it as their own reviewed content. A section with
  // `needs_review` holds a sample/AI draft that is NOT yet filable.
  content_origin?: "uploaded" | "generated" | "sample" | "ai_draft" | null;
  content_confirmed?: boolean;
  needs_review?: boolean;
}

export interface ModuleProgress {
  required_total: number;
  required_filled: number;
  percent: number;
  complete: boolean;
}

export interface ModuleView {
  module: string;
  title: string;
  nodes: SectionNode[];
  progress: ModuleProgress;
}

export interface Leaf {
  leaf_id: string;
  title: string;
  href: string;
  checksum: string;
  operation: string;
}

export interface FilesView {
  dossier_id: string;
  placement_version: string;
  nodes: { heading: string; title: string; folder: string; leaves: Leaf[] }[];
  live_leaf_count: number;
}

export interface OutlineView {
  dossier_id: string;
  sequence: string;
  backbone: { "index.xml": string; "ca-regional.xml": string };
  lifecycle_operations: { leaf_id: string; operation: string; sequence: string }[];
}

export interface FeesBlock {
  review_fee: { fiscal_year: string; amount: number; currency: string; basis: string };
  mitigation: { reduction: number; waived: boolean; payable: number; note: string };
  right_to_sell: { amount: number; due_date: string; note: string };
  fee_paid: boolean;
  sme_granted: boolean;
}

// A single structural/format finding. `leaf` is the failing file/leaf id.
export interface ValidationFinding {
  rule: string;
  rule_id?: string;
  message: string;
  leaf?: string | null;
}

// The named, versioned validator profile + an honest coverage statement.
// This is what makes the green checkmark truthful: it says WHAT was checked
// (presence/format) and — explicitly — what was NOT (scientific adequacy,
// full eCTD technical validation, Health Canada acceptance).
export interface ValidationCriteria {
  name: string;
  version: string;
  // When the rule set was last reconciled against the published HC criteria.
  synced?: string;
  modeled_on: string;
  disclaimer: string;
  coverage: {
    checked: string[];
    not_checked: string[];
  };
}

// ADOPT-EVALIDATOR: a USER-ATTESTED external validator result. ANDS Studio
// cannot run Health Canada's official eValidator, so this is the filer's real
// outcome of running eValidator (or their publisher's validator) on the
// EXPORTED package, attached as external evidence. `source` is fixed to
// "user_attested_external" — it is NEVER a tool self-claim of parity.
export interface EvalidatorAttestation {
  source: "user_attested_external";
  result: "pass" | "fail";
  validator_name: string;
  validator_version?: string | null;
  validated_on?: string | null;
  attested_by?: string | null;
  notes?: string | null;
  report_filename?: string | null;
  disclaimer: string;
  recorded_at?: string;
  updated_at?: string;
}

export interface EvalidatorAttestationResponse {
  dossier_id: string;
  attestation: EvalidatorAttestation | null;
}

// ADOPT-PART11-ESIGN: a REAL 21 CFR Part 11-aligned e-signature manifest — the
// signer identity, the meaning + human REASON, a UTC timestamp, and a
// tamper-evident hash bound over the exact checksummed eCTD leaf set.
export interface EsignManifestLeaf {
  id: string;
  kind?: string;
  checksum: string;
  checksum_type?: string;
}
export interface EsignManifest {
  signer: string;
  role?: string;
  auth_method?: string;
  meaning?: string;
  reason?: string;
  at?: string;
  tz?: string;
  manifest_id: string;
  leaf_count?: number;
  artifacts?: EsignManifestLeaf[];
  policy?: string;
  immutable?: boolean;
  updated_at?: string;
}
export interface EsignVerificationFinding {
  rule: string;
  artifact: string;
  signed_checksum?: string;
  current_checksum?: string;
  message: string;
}
export interface EsignVerification {
  signed: boolean;
  verified: boolean;
  tampered: boolean;
  findings: EsignVerificationFinding[];
  manifest_id: string;
  signer?: string;
  reason?: string;
  signed_at?: string;
  leaf_count?: number;
}

export interface ValidationResult {
  passed: boolean;
  errors: ValidationFinding[];
  warnings: ValidationFinding[];
  checked: number;
  // present on the full validate() result and export-block bodies
  criteria?: ValidationCriteria;
  // ADOPT-EVALIDATOR: the user-attested external eValidator result, surfaced
  // ALONGSIDE the structural check (it never drives `passed`). null/absent when
  // the filer has not attached one yet.
  external_attestation?: EvalidatorAttestation | null;
}

// One rule in the queryable catalogue (GET /api/dossier/validation/rules).
export interface ValidationRule {
  rule: string;
  rule_id: string;
  family: string;
  severity: "error" | "warning";
  description: string;
  // The HC/ICH source clause this rule is modeled on (v1.2+).
  source?: string;
}

export interface ValidationRuleCatalog {
  count: number;
  rules: ValidationRule[];
  criteria: ValidationCriteria;
}

// The verdict block the export gate returns inside a 409 problem body when
// validation does not pass (fail-closed). `ran=false` => the validator itself
// could not run, so export is blocked as "validation_unavailable".
export interface ExportValidationVerdict {
  passed: boolean;
  ran: boolean;
  errors: ValidationFinding[];
  criteria: ValidationCriteria;
}

// GET /ectd/{id}/export/{sequence} → 409 problem+json when blocked.
export interface ExportBlocked {
  ok: false;
  status: number; // 409 (validation_not_passed / validation_unavailable) | other
  title: string;
  detail?: string;
  validation?: ExportValidationVerdict;
}

// Successful export: the transmissible package blob + its validation stamp.
export interface ExportOk {
  ok: true;
  blob: Blob;
  filename: string;
  stamp: "passed" | "overridden" | "unknown" | null; // X-Export-Validation
}

export type ExportOutcome = ExportOk | ExportBlocked;

export interface ContentState {
  dossier_id: string;
  cs_be_only: boolean;
  version: string;
  modules: ModuleView[];
  gate: {
    complete: boolean;
    missing: { section: string; title: string; module: string;
               needs_review?: boolean }[];
    section_complete?: boolean;
    fee_paid?: boolean;
    validation_passed?: boolean;
    // WS2: how many sections still hold an unconfirmed sample/AI draft
    unconfirmed_sample_count?: number;
  };
  tower: ModuleTower[];
  fees: FeesBlock;
  validation: ValidationResult;
  din: string | null;
  files_view: FilesView | null;
}

// working sequences (0001+) + regulatory-response lifecycle
export type SequencePurpose =
  | "initial"
  | "response"
  | "supplement"
  | "annual-notification";

export interface SequenceInfo {
  sequence: string;
  purpose: SequencePurpose | string;
  note: string;
  leaf_count: number;
  active: boolean;
}

export interface SequenceList {
  dossier_id: string;
  active_sequence: string;
  sequences: SequenceInfo[];
}

// -- eCTD current view: the live leaf set + retired history, each carrying its
// lifecycle operator (new/replace/append/delete) — GET /ectd/{id}/current-view.
export interface CurrentViewLeaf {
  leaf_id: string;
  title: string;
  heading: string;
  href: string;
  operation: "new" | "replace" | "append" | "delete" | string;
  sequence: string;
  checksum: string;
  modified_leaf: string | null;
}

export interface CurrentView {
  live: CurrentViewLeaf[];
  history: CurrentViewLeaf[];
}

// -- bilingual Product Monograph status (REQ-098) — GET /monograph/status.
// A missing EN or FR leaf is a transmission BLOCKER; EN newer than FR is a
// non-blocking Plain-Language-Labelling sync warning.
export interface MonographLeaf {
  dossier_id: string;
  lang: "en" | "fr";
  leaf_id: string;
  title: string;
  version: number;
  heading: string;
}

export interface MonographFinding {
  rule: string;
  severity: "blocking" | "warning";
  message: string;
}

export interface MonographStatus {
  status: "complete" | "blocked";
  blocking: boolean;
  findings: MonographFinding[];
  pair: { en: MonographLeaf | null; fr: MonographLeaf | null };
}

// -- XML Product Monograph validation (REQ-099) — POST /monograph/xml/validate.
export interface PmXmlValidation {
  valid: boolean;
  blocking: boolean;
  findings: { rule: string; severity: string; message: string;
              code?: string; field?: string }[];
}

export interface DossierIndex {
  dossier_id: string;
  title: string;
  submission_type: string;
  cs_be_only: boolean;
  // present only when the dossier is actually registered (a real DB row);
  // absent on the tolerant fallback the API returns for unregistered ids
  created_at?: string;
  din?: string | null;
  tenant_id?: string | null;
  // REP identity — the sponsor/client company (distinct from the product title)
  company_id?: string | null;
  sponsor?: string | null;
  // WS6 portfolio: the accountable PM/owner for this dossier
  owner?: string | null;
}

export interface DossierListItem extends DossierIndex {
  tower: ModuleTower[];
  gate: { complete: boolean; missing: any[] };
  // WS6: soonest upcoming deadline, derived server-side from content-plan items
  soonest_due?: string | null;
}

export interface DossierFull {
  index: DossierIndex;
  content: ContentState;
}
