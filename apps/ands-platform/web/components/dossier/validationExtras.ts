// ROUND9-VALIDATE — shared helpers for the validate/export flow.
//
// The backend's criteria() gained round-9 fields (staleness, checksum_note)
// and rule_catalog() gained how_to_fix. The shared ValidationCriteria /
// ValidationRule types live in lib/dossierTypes.ts (not owned by this flow),
// so the new fields are accessed through the local extension accessors below
// — no edit to the shared type file, no `any` leaks at call sites.
import type {
  CurrentView,
  ValidationCriteria,
  ValidationFinding,
  ValidationRule,
} from "@/lib/dossierTypes";

// -- item 1: the loud review-overdue staleness block (criteria().staleness) --
export interface CriteriaStaleness {
  review_overdue: boolean;
  as_of: string;
  synced_to: string;
  next_review: string;
  message: string;
  verify_at: string;
  limitation: string;
}

export function criteriaStaleness(
  c?: ValidationCriteria
): CriteriaStaleness | null {
  const s = (c as unknown as { staleness?: CriteriaStaleness } | undefined)
    ?.staleness;
  return s ?? null;
}

// -- item 10: the "md5 computed exactly as eCTD 3.2.2 expects" note --------
export function criteriaChecksumNote(c?: ValidationCriteria): string {
  return (
    (c as unknown as { checksum_note?: string } | undefined)?.checksum_note ??
    ""
  );
}

// -- item 14: the one-line how-to-fix hint per rule -------------------------
export function ruleHowToFix(r?: ValidationRule | null): string {
  return (
    (r as unknown as { how_to_fix?: string } | null | undefined)?.how_to_fix ??
    ""
  );
}

// Index the live rule catalogue by rule_id AND machine rule name so a finding
// can be joined to its catalogue row (source citation + how-to-fix hint).
export function indexRules(
  rules: ValidationRule[] | null | undefined
): Map<string, ValidationRule> {
  const m = new Map<string, ValidationRule>();
  for (const r of rules ?? []) {
    if (r.rule_id && !m.has(r.rule_id)) m.set(r.rule_id, r);
    if (r.rule && !m.has(r.rule)) m.set(r.rule, r);
  }
  return m;
}

export function ruleForFinding(
  idx: Map<string, ValidationRule>,
  f: ValidationFinding
): ValidationRule | null {
  return (f.rule_id && idx.get(f.rule_id)) || idx.get(f.rule) || null;
}

// -- item 14/2: resolve the module (m1..m5) that owns a finding's leaf ------
// Primary: look the leaf up in the eCTD current view and read its href's
// module folder. Fallback: an m1..m5 prefix on the leaf id / href-like string
// itself. Returns "m1".."m5" or null when unresolvable (then no link is shown
// — never a wrong link).
export function moduleOfLeaf(
  leaf: string | null | undefined,
  view: CurrentView | null
): string | null {
  if (!leaf) return null;
  const all = view ? [...view.live, ...view.history] : [];
  const hit = all.find((l) => l.leaf_id === leaf);
  const href = hit?.href || "";
  let m = /^m([1-5])\//.exec(href);
  if (m) return `m${m[1]}`;
  m = /^m([1-5])[-/_.]/.exec(leaf);
  if (m) return `m${m[1]}`;
  return null;
}

// The module workspace route uses a bare digit segment (…/m/1), see
// app/dossiers/[dossierId]/m/[module]/page.tsx.
export function modulePath(dossierId: string, mod: string): string {
  const digit = mod.replace(/^m/, "");
  return `/dossiers/${encodeURIComponent(dossierId)}/m/${digit}`;
}

// -- item 15: the direct auto-placement statement (one canonical copy) ------
export const AUTO_PLACEMENT_STATEMENT =
  "Leaves are placed automatically from the module pages upstream — no " +
  "manual per-document leaf placement is needed before this check runs.";

// -- item 2: the honest sponsor-scoping / ruleset-pinning statement ---------
export const SPONSOR_SCOPE_STATEMENT =
  "Findings are scoped to this dossier's sponsor workspace (the hard tenant " +
  "boundary — cross-workspace reads are refused at the API layer).";

export const RULESET_PINNING_LIMIT =
  "The ruleset applies workspace-wide; every run and report is stamped with " +
  "the exact version it ran against. Per-sponsor ruleset-version pinning is " +
  "not yet supported.";
