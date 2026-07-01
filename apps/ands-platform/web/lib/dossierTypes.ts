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
  origin: "uploaded" | "generated";
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

export interface ValidationResult {
  passed: boolean;
  errors: { rule: string; message: string; leaf?: string }[];
  warnings: { rule: string; message: string; leaf?: string }[];
  checked: number;
}

export interface ContentState {
  dossier_id: string;
  cs_be_only: boolean;
  version: string;
  modules: ModuleView[];
  gate: {
    complete: boolean;
    missing: { section: string; title: string; module: string }[];
    section_complete?: boolean;
    fee_paid?: boolean;
    validation_passed?: boolean;
  };
  tower: ModuleTower[];
  fees: FeesBlock;
  validation: ValidationResult;
  din: string | null;
  files_view: FilesView | null;
}

export interface DossierIndex {
  dossier_id: string;
  title: string;
  submission_type: string;
  cs_be_only: boolean;
}

export interface DossierListItem extends DossierIndex {
  tower: ModuleTower[];
  gate: { complete: boolean; missing: any[] };
}

export interface DossierFull {
  index: DossierIndex;
  content: ContentState;
}
