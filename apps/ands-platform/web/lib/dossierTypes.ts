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

// FORMS-WEB: the declarative form schema the web renders every eCTD content
// section by (upload + form-fill + per-field AI-draft + generate). Mirrors the
// shared FORM-SCHEMA CONTRACT in services/dossier/app/form_schemas.py.
export type FieldType =
  | "text"
  | "textarea"
  | "date"
  | "select"
  | "email"
  | "number";

export interface FormField {
  name: string;
  label: string;
  type: FieldType;
  required: boolean;
  // prose:true — a free-text field the filer can AI-draft one field at a time.
  prose: boolean;
  // an HC-grounded one-liner telling the filer what Health Canada expects here.
  help: string;
  options?: string[];
  placeholder?: string;
  sample?: string;
  // a bilingual (EN + FR) field per the HC template.
  bilingual?: boolean;
}

export interface FormSchema {
  section: string;
  title: string;
  description: string;
  // "structured" (universal PDF from the filled fields) OR a bespoke key.
  generator: string;
  fields: FormField[];
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
  // Each op carries the prior-leaf back-pointer (``modified_leaf``) for
  // replace/append/delete so a publisher can see lifecycle correctness — the
  // backbone (build_outline_view) has always returned it; the type now reflects
  // that (ADOPT-LIFECYCLE-0001).
  lifecycle_operations: {
    leaf_id: string;
    operation: string;
    sequence: string;
    modified_leaf: string | null;
  }[];
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
  // CAMP-CRITERIA-SYNC: the maintenance-cadence commitment, embedded so it
  // travels with every validation surface (last/next review + how it's kept).
  review?: CriteriaReview;
  modeled_on: string;
  disclaimer: string;
  coverage: {
    checked: string[];
    not_checked: string[];
  };
}

// CAMP-CRITERIA-SYNC: the "last reviewed / next review" maintenance cadence — a
// buyer's proof the ruleset is maintained, not stale.
export interface CriteriaReview {
  cadence: string;
  last_reviewed: string;
  next_review: string;
  process?: string;
}

// CAMP-CRITERIA-SYNC: one auditable entry in the criteria-sync trail — a profile
// version, when it was reconciled to HC's published criteria, and what changed.
export interface CriteriaHistoryEntry {
  version: string;
  date: string;
  synced_to: string;
  changes: string[];
}

// CAMP-CRITERIA-SYNC: the full criteria-sync transparency payload — the
// versioned profile, the newest-first version history, and the review cadence.
export interface CriteriaHistory {
  criteria: ValidationCriteria;
  history: CriteriaHistoryEntry[];
  review: CriteriaReview;
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
  // TIER2-PARITY-UX: the ACTUAL attached eValidator report FILE (bytes stored
  // in the byte store) — surfaced as downloadable evidence, not just a filename.
  report_doc_id?: string | null;
  report_content_type?: string | null;
  report_size?: number | null;
  report_checksum?: string | null;
  report_attached_by?: string | null;
  report_attached_at?: string | null;
}

export interface EvalidatorAttestationResponse {
  dossier_id: string;
  attestation: EvalidatorAttestation | null;
}

// POLISH-EVAL-CLEARED: the FIRST-CLASS "eValidator-cleared" state (the
// ra_director/ra_officer ask). `cleared` is true only when the user attested a
// PASS result AND attached the actual report file (report_doc_id present) — a
// bare pass, or a report without a pass, is honestly NOT cleared. It is
// USER-ATTESTED EXTERNAL evidence, never an ANDS Studio self-claim of HC
// eValidator parity; the `source` label + `disclaimer` always travel with it.
export interface EvalidatorClearedState {
  source: "user_attested_external";
  cleared: boolean;
  result: "pass" | "fail" | null;
  report_present: boolean;
  validator_name?: string | null;
  validator_version?: string | null;
  validated_on?: string | null;
  attested_by?: string | null;
  report_doc_id?: string | null;
  report_filename?: string | null;
  report_attached_at?: string | null;
  disclaimer: string;
}

// TIER2-PARITY-UX: the response from attaching the eValidator report file.
export interface EvalidatorReportResponse {
  dossier_id: string;
  attestation: EvalidatorAttestation;
}

// TIER2-PARITY-UX: self-serve STRUCTURAL validation of a single sequence.
// Same shape as ValidationResult, scoped to one sequence (never a filing
// verdict or an HC eValidator parity claim).
export interface SequenceValidationResult extends ValidationResult {
  dossier_id: string;
  sequence: string;
  scope: "sequence";
}

// CAMP-INTEROP: the import-compatibility self-check the tool runs over its OWN
// exported package — the structural contract any compliant RIM importer (Vault
// RIM / docuBridge / eValidator) relies on. HONEST: verifies the STANDARD
// contract; it does NOT certify a specific vendor.
export interface ImportCompatCheck {
  id: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface ImportCompatLeaf {
  leaf_id: string;
  operation: string;
  href: string;
  resolved: boolean;
  cross_sequence: boolean;
}

export interface ImportCompatInventory {
  root: string;
  index_xml: string;
  index_md5: string;
  ca_regional: string;
  util_dtds: string[];
  modules: string[];
  files: string[];
}

export interface ImportCompatReport {
  compatible: boolean;
  checks: ImportCompatCheck[];
  errors: { id: string; label: string; detail: string }[];
  passed_count: number;
  check_count: number;
  inventory: ImportCompatInventory;
  leaves: ImportCompatLeaf[];
  file_count: number;
  dossier_id: string;
  sequence: string;
  filename: string;
  standard: { ectd: string; regional: string };
  disclaimer: string;
}

// CAMP-SHADOW — the shadow / parallel-run comparison. The tool runs its OWN
// structural validator + import-compat self-check over a prior/known-good
// sequence and lays the result out diff-friendly so a filer can line it up
// against a filing they KNOW passed eValidator. HONEST: a confidence-building
// comparison of structural output, NOT a guarantee, and it never drives the
// filing gate.
export interface ShadowLeafRow {
  leaf_id: string;
  href: string;
  md5: string;
  operation: string;
  title: string;
  heading: string;
}

export interface ShadowLifecycleOp {
  leaf_id: string;
  operation: string;
  modified_leaf: string | null;
}

export interface ShadowMatchedRow {
  leaf_id: string;
  tool_href: string;
  reference_href: string | null;
  tool_md5: string | null;
  reference_checksum: string | null;
  checksum_match: "match" | "mismatch" | "unknown";
  operation: string;
}

export interface ShadowDiff {
  identical: boolean;
  matched: ShadowMatchedRow[];
  checksum_mismatch: ShadowMatchedRow[];
  only_in_tool: {
    leaf_id: string;
    href: string;
    md5: string;
    operation: string;
  }[];
  only_in_reference: {
    leaf_id: string;
    href: string | null;
    checksum: string | null;
  }[];
  matched_count: number;
  tool_leaf_count: number;
  reference_leaf_count: number;
}

export interface ShadowRunReport {
  mode: "shadow";
  dossier_id: string;
  sequence: string;
  validation: {
    passed: boolean;
    errors: { code?: string; message?: string; [k: string]: unknown }[];
    warnings: { code?: string; message?: string; [k: string]: unknown }[];
    criteria: Record<string, unknown> & { disclaimer?: string };
  };
  import_compat: ImportCompatReport;
  leaf_inventory: ShadowLeafRow[];
  leaf_count: number;
  lifecycle_operations: ShadowLifecycleOp[];
  has_reference: boolean;
  diff: ShadowDiff | null;
  disclaimer: string;
}

// A publisher-style known-good reference leaf the filer supplies to diff
// against (only leaf_id / href / checksum are used).
export interface ShadowReferenceLeaf {
  leaf_id: string;
  href?: string;
  checksum?: string;
}

// TIER2-PARITY-UX: a PREPARED (not transmitted) REP Dossier-ID Request.
export interface RepRequest {
  transmitted: false;
  dossier_id: string;
  placeholder: boolean;
  company_id?: string | null;
  sponsor?: string | null;
  activity_type?: string | null;
  contact_email?: string | null;
  note?: string | null;
  requested_by?: string | null;
  requested_at?: string;
  updated_at?: string;
  guidance: {
    summary: string;
    steps: string[];
    url: string;
  };
}

export interface RepRequestResponse {
  dossier_id: string;
  rep_request: RepRequest | null;
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
// TIER2-ROLE-SEP: the segregation-of-duties outcome recorded with a signature —
// whether the signer is a DISTINCT authorized approver from the author(s) of
// the signed content. Honesty: a role-separation check, NOT an SSO/IdP claim.
export interface SegregationOfDuties {
  separated: boolean;
  conflict: boolean;
  authorship_known: boolean;
  signer: string;
  authors: string[];
  author_count: number;
  conflicting_authors: string[];
  reason: string;
  enforced?: boolean;
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
  segregation_of_duties?: SegregationOfDuties;
}
// The distinct author identities recorded for a dossier's content — the set a
// signer is checked against for segregation of duties.
export interface ContentAuthors {
  dossier_id: string;
  authors: string[];
  author_count: number;
  by_section: Record<string, string>;
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
  // POLISH-EVAL-CLEARED: the first-class user-attested "eValidator-cleared"
  // state (pass + attached report) travels alongside the structural result and
  // never drives `passed`.
  evalidator_cleared?: EvalidatorClearedState;
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

// TIER3-PREFLIGHT: ONE consolidated pre-flight / QA hand-off report — the whole
// filing-readiness picture assembled into a single archivable object. RESOLVES
// the "re-run validate at each step" limit. Every honesty disclaimer travels
// INLINE (see `disclaimers`); the readiness `summary`/`claim` are STRUCTURAL
// statements and never assert Health Canada acceptance.
// FIX-PREFLIGHT-SIG: the consolidated report shows the LATEST stored manifest +
// a LIVE verify. After later leaf changes (e.g. a 0001 replace) or a conflict-
// demo sign, the current signature is legitimately stale/unverified/conflicted.
// This one status collapses (signed? / verify passes? / SoD conflict?) into an
// unambiguous verdict a QA reviewer can act on — never a bare verified=false.
export type SignatureStatus =
  | "unsigned"
  | "verified"
  | "stale_unverified"
  | "sod_conflict";
export interface PreflightReadiness {
  ready: boolean;
  structural_errors: number;
  structural_warnings: number;
  signed: boolean;
  signature_verified: boolean;
  signature_status: SignatureStatus;
  handoff_ready_signature: boolean;
  signature_message: string;
  fee_arranged: boolean;
  evalidator_attested: boolean;
  // POLISH-EVAL-CLEARED: first-class user-attested cleared bool (pass + report).
  evalidator_cleared: boolean;
  placeholder_dossier_id: boolean;
  summary: string;
  claim: string;
  next_step: string;
}
export interface PreflightEsign {
  signed: boolean;
  manifest: EsignManifest | null;
  segregation_of_duties?: SegregationOfDuties | null;
  verification: EsignVerification;
  signature_status: SignatureStatus;
  handoff_ready_signature: boolean;
  message: string;
}
export interface PreflightReport {
  dossier_id: string;
  title: string;
  drug_product?: string | null;
  sponsor?: string | null;
  submission_type?: string | null;
  din?: string | null;
  generated_at: string;
  readiness: PreflightReadiness;
  validation: ValidationResult;
  evalidator_attestation: EvalidatorAttestation | null;
  // POLISH-EVAL-CLEARED: the full first-class cleared block on the report.
  evalidator_cleared: EvalidatorClearedState;
  esign: PreflightEsign;
  fees: FeesBlock | null;
  sequences: SequenceList;
  rep: {
    dossier_id: string;
    placeholder: boolean;
    rep_request: RepRequest | null;
  };
  // one honest caveat per string — consolidated, never laundered away.
  disclaimers: Record<string, string>;
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
  // the submission type driving the content model; scope_note is a plain-
  // language caveat for non-ANDS types (null for a fully-supported ANDS).
  submission_type?: string;
  scope_note?: string | null;
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
  // POLISH-EVAL-CLEARED: the first-class "eValidator-cleared" state on the
  // dossier itself, so the workspace can render a cleared / not-yet-cleared chip.
  evalidator: EvalidatorClearedState;
  // POLISH-SIGN-BANNER: ambient signature-readiness signal so the workspace
  // chrome can show a PERSISTENT "not cleanly signed — re-sign required" banner
  // the moment a leaf changes after signing or a conflicted sign occurs. Reuses
  // the same _signature_status the pre-flight computes (role-separation +
  // tamper-evidence, NOT a Health Canada acceptance claim).
  signature_readiness: SignatureReadiness;
  files_view: FilesView | null;
}

export interface SignatureReadiness {
  signed: boolean;
  status: SignatureStatus;
  handoff_ready: boolean;
  // the loud-banner trigger: signed AND the current signature is not verified
  // (stale/conflicted). Unsigned is a normal pre-sign state and does NOT trip it.
  needs_resign: boolean;
  message: string;
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
