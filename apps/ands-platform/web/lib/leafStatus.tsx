// ONE status vocabulary for the whole eCTD builder. The section tree, the
// M1–M5 module tabs, and the readiness/gate card all read from this map so a
// filer learns the icon + word + colour once and it means the same thing in
// every column. (Unified build spec P0-1/2/3, P0-4, P1-4.)
//
// The `review` state is the crucial one: a leaf whose bytes are present but
// which holds an unconfirmed sample/AI draft (`needs_review`) is NOT filable
// and the export gate rejects it — so it must NOT show the "complete" check.
// `effectiveLeafStatus` folds needs_review over the raw placement status.
import {
  Circle,
  CircleDashed,
  CheckCircle2,
  MinusCircle,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react";
import type { SectionNode, SectionStatus } from "./dossierTypes";

// The single status axis every builder surface renders.
export type LeafState = "empty" | "partial" | "complete" | "review" | "na";

export interface LeafStatusMeta {
  icon: LucideIcon;
  /** short word shown in the row micro-line + tooltip */
  word: string;
  /** full sentence for the Radix tooltip / aria-label */
  help: string;
  /** the Prism colour token this state paints with */
  color: string;
  /** the css modifier class (drives the 3px accent bar tint) */
  cls: LeafState;
}

export const LEAF_STATUS: Record<LeafState, LeafStatusMeta> = {
  empty: {
    icon: Circle,
    word: "Not started",
    help: "Not started — no document placed at this eCTD leaf yet.",
    color: "var(--mut)",
    cls: "empty",
  },
  partial: {
    icon: CircleDashed,
    word: "In progress",
    help: "In progress — some content is placed but this leaf is not complete.",
    color: "var(--warn)",
    cls: "partial",
  },
  complete: {
    icon: CheckCircle2,
    word: "Complete",
    help: "Complete — a reviewed document is placed at this eCTD leaf.",
    color: "var(--ok)",
    cls: "complete",
  },
  review: {
    icon: AlertTriangle,
    word: "Review required",
    help:
      "Placed — but not yet filable. This leaf holds a sample or AI draft that " +
      "must be reviewed and confirmed as your own content before the submission " +
      "can be exported.",
    color: "var(--warn)",
    cls: "review",
  },
  na: {
    icon: MinusCircle,
    word: "N/A",
    help: "Not applicable — marked N/A for this submission; nothing to file here.",
    color: "var(--mut)",
    cls: "na",
  },
};

// Fold `needs_review` over the raw placement status so a placed-but-unconfirmed
// sample/AI leaf never renders the green "complete" check the export gate would
// reject. A placement status the map doesn't know falls back to "empty".
export function effectiveLeafStatus(n: {
  status: SectionStatus;
  needs_review?: boolean;
}): LeafState {
  if (n.needs_review) return "review";
  return (["empty", "partial", "complete", "na"] as const).includes(
    n.status as any
  )
    ? (n.status as LeafState)
    : "empty";
}

// The applicability sentence for the tooltip (required vs optional).
export function applicabilityHelp(a: SectionNode["applicability"]): string {
  if (a === "required")
    return "Required by Health Canada for this submission type.";
  if (a === "optional")
    return "Optional — include when it applies, otherwise Mark N/A with a reason.";
  return "Not applicable for this submission model.";
}

// ── eCTD lifecycle operator (new/replace/append/delete) ──────────────────
// Shown per leaf so the operator — the heart of eCTD lifecycle — is visible at
// authoring time, not assumed. replace/delete carry risk (they act on a live
// leaf) so they get an attention tint.
export type LeafOp = "new" | "replace" | "append" | "delete";

export const OP_META: Record<LeafOp, { label: string; word: string; risk: boolean }> = {
  new: { label: "NEW", word: "new leaf", risk: false },
  replace: { label: "REPL", word: "replace leaf", risk: true },
  append: { label: "APP", word: "append leaf", risk: false },
  delete: { label: "DEL", word: "delete leaf", risk: true },
};

export function opMeta(op?: string | null): { label: string; word: string; risk: boolean } | null {
  if (!op) return null;
  return OP_META[op as LeafOp] ?? { label: op.toUpperCase(), word: `${op} leaf`, risk: false };
}

// Short human name per eCTD module (for tab + tree-header aria-labels). The
// long "requirement satisfied" copy lives in TowerChecklist.MODULE_REQ.
export const MODULE_NAME: Record<string, string> = {
  "1": "Administrative & regional (Canada)",
  "2": "CTD summaries",
  "3": "Quality (CMC)",
  "4": "Nonclinical",
  "5": "Clinical (comparative BE)",
};

// The module-tab roll-up state, derived from the ModuleTower plus a
// needs-review signal, using the SAME LeafState vocabulary as the tree.
export type ModuleTabState = "todo" | "partial" | "complete" | "review" | "na";

