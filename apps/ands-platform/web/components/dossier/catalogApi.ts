// Round-9 Dossier Catalog (`catalog`) — client extensions over the same
// /api/dossier proxy that dossierApi uses. Kept beside the catalog components
// (not in lib/) so the catalog surface owns its round-9 payload contract:
//  - the named-clock soonest-due meta ("'Soonest due' dates have no defined
//    source or regulatory clock", n=8),
//  - the REP request summary ("REP Dossier ID Request flow unexplained and
//    untracked", n=7),
//  - lifecycle + live structural summary ("List view lacks sequence/lifecycle
//    and validation status", n=4),
//  - bilingual PM status + governed FR product name ("No bilingual/French
//    support surfaced anywhere on the page", n=2),
//  - typed-name e-signature capture on archive/restore + Owner reassignment
//    ("No user roles, permissions, or e-signatures on workspace actions", n=6).
import { friendlyError } from "@/lib/friendlyError";
import type { DossierListItem } from "@/lib/dossierTypes";

const BASE = "/api/dossier";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const b = await res.json();
      detail = [b.title, b.detail].filter(Boolean).join(": ") || detail;
    } catch {}
    throw new Error(friendlyError(res.status, detail));
  }
  return res.json() as Promise<T>;
}

// The NAMED clock behind a catalog due date. HONEST: every catalog soonest-due
// is a client-set target carried on a content-plan item — HC statutory clocks
// (45-day screening, response windows) come from real HC notices on the
// Portfolio/Correspondence surfaces; the catalog never fabricates one.
export interface SoonestDueMeta {
  date: string;
  clock_type: string; // "client-set target"
  item_id: string;
  item_title: string;
  assignee: string | null;
}

export interface RepRequestSummary {
  transmitted: false; // honesty flag — a PREPARED request, never a transmission
  requested_at: string;
  requested_by?: string | null;
  activity_type?: string | null;
}

export interface LifecycleBlock {
  active_sequence: string;
  sequence_count: number;
  purpose: string;
}

export interface StructuralSummary {
  passed: boolean;
  error_count: number;
  warning_count: number;
}

export interface EvalidatorSummary {
  source: string; // "user_attested_external"
  cleared: boolean;
  result: string | null;
  validated_on?: string | null;
}

export interface BilingualPmBlock {
  status: "none" | "blocked" | "complete" | string;
  en: boolean;
  fr: boolean;
}

// A catalog row with every round-9 block the list endpoint now carries.
export type CatalogListItem = DossierListItem & {
  soonest_due_meta?: SoonestDueMeta | null;
  rep_request?: RepRequestSummary | null;
  lifecycle?: LifecycleBlock;
  structural?: StructuralSummary;
  evalidator?: EvalidatorSummary;
  bilingual_pm?: BilingualPmBlock;
  title_fr?: string | null;
  labelling_owner?: string | null;
};

export interface PlanItem {
  id: string;
  title: string;
  status: string;
  assignee?: string | null;
  due_date?: string | null;
}

// Typed-name e-signature capture (catalog n=6). HONEST: the signer's typed
// full name + the displayed meaning, recorded verbatim on the durable ledger —
// a typed-name capture, not a cryptographic certificate.
export interface EsignCapture {
  signed_name: string;
  meaning: string;
}

// New-dossier body incl. the round-9 bilingual fields (governed FR product
// name + labelling owner) the shared lib client does not carry yet.
export interface CreateDossierBody {
  dossier_id: string;
  title?: string;
  title_fr?: string;
  submission_type?: string;
  cs_be_only?: boolean;
  // TIER-A: dosage form driving the comparative-evidence route (generic family)
  dosage_form_class?: string;
  // TIER-B: product class (for the honest out-of-core scope note)
  product_class?: string;
  sponsor?: string;
  owner?: string;
  labelling_owner?: string;
}

export const catalogApi = {
  listDossiers: () =>
    j<{ dossiers: CatalogListItem[]; count: number }>("/dossiers"),

  createDossier: (body: CreateDossierBody) =>
    j<CatalogListItem>("/dossiers",
      { method: "POST", body: JSON.stringify(body) }),

  listArchived: () =>
    j<{ dossiers: (CatalogListItem & { archived_at?: string;
        archived_by?: string; archive_reason?: string })[]; count: number }>(
      "/dossiers/archived"),

  // archive with the optional typed-name e-signature riding on the durable
  // ledger event (server keeps the typed-confirm + reason gate unchanged)
  archiveDossier: (id: string, reason: string, confirmId: string,
                   esign?: EsignCapture) =>
    j<{ archived: string; reason: string; recoverable: boolean }>(
      `/dossiers/${encodeURIComponent(id)}`,
      { method: "DELETE",
        body: JSON.stringify({ reason, confirm_id: confirmId,
                               ...(esign ? { esign } : {}) }) }),

  restoreDossier: (id: string, reason: string, esign?: EsignCapture) =>
    j<{ restored: string; reason: string }>(
      `/dossiers/${encodeURIComponent(id)}/restore`,
      { method: "POST",
        body: JSON.stringify({ reason, ...(esign ? { esign } : {}) }) }),

  // Owner (PM) reassignment — an accountability label (roles govern
  // permissions); old/new + reason land on the durable ledger.
  setOwner: (id: string, owner: string, reason: string) =>
    j<{ dossier_id: string; owner: string | null; reason: string }>(
      `/dossiers/${encodeURIComponent(id)}/owner`,
      { method: "POST", body: JSON.stringify({ owner, reason }) }),

  // content-plan reads/writes backing the in-place due-date entry: the
  // catalog "Soonest due" is DERIVED from plan items, so editing the date
  // edits the DRIVING ITEM (named on the clock label), not a free date field.
  // null = no plan yet (404) — the caller then creates one; any OTHER failure
  // still throws so a transient error never silently spawns a duplicate plan.
  getPlan: async (dossierId: string) => {
    const res = await fetch(
      `${BASE}/content-plans?dossier_id=${encodeURIComponent(dossierId)}`,
      { headers: { "content-type": "application/json" }, cache: "no-store" });
    if (res.status === 404) return null;
    if (!res.ok) {
      let detail = `${res.status}`;
      try {
        const b = await res.json();
        detail = [b.title, b.detail].filter(Boolean).join(": ") || detail;
      } catch {}
      throw new Error(friendlyError(res.status, detail));
    }
    return res.json() as Promise<{ plan: { id: string; items: PlanItem[] } }>;
  },

  createPlan: (dossierId: string, submissionType: string, csBeOnly: boolean) =>
    j<{ plan: { id: string; items: PlanItem[] } }>(
      "/content-plans",
      { method: "POST",
        body: JSON.stringify({ dossier_id: dossierId,
                               submission_type: submissionType || "ANDS",
                               cs_be_only: csBeOnly }) }),

  assignItem: (itemId: string, assignee: string, dueDate: string) =>
    j<{ item: PlanItem }>(
      "/content-plans/item/assign",
      { method: "POST",
        body: JSON.stringify({ id: itemId, assignee, due_date: dueDate }) }),
};
