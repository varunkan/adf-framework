// Round-9 ai_draft/builder_forms — client for the drafting-transparency and
// attestation endpoints added in services/dossier (same /api/dossier proxy +
// problem+json handling as lib/dossierApi; kept HERE so the drafting panel
// owns its own contract). Backlog anchors per method below.
import { friendlyError } from "@/lib/friendlyError";
import type { ContentState, DocMeta, SectionNode } from "@/lib/dossierTypes";

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

// The round-9 per-section state the server now annotates on every node
// (dossier_state.annotate) — typed locally; lib/dossierTypes is not extended
// from here.
export type SectionNodeR9 = SectionNode & {
  ai_disabled?: boolean;
  attestation?: {
    name: string;
    credential: string;
    meaning: string;
    attested_at: string;
    actor: string;
  } | null;
  sample_fields?: string[];
  content_author?: string | null;
  updated_at?: string | null;
  // the exact saved AI draft text (ai_draft origin only) — powers the
  // scroll-to-attest gate and the side-by-side review.
  draft_text?: string | null;
};

// GET /ai-provider — ai_draft BLOCKER "AI provider identity, data residency
// and DPA not verifiable" (n=8).
export interface ProviderDisclosure {
  configured: boolean;
  provider: string;
  model: string;
  endpoint: string;
  hosting_region: string;
  leaves_canada: boolean;
  data_residency: string;
  retention: string;
  isolation: string;
  training: string;
  policy_url: string;
  dpa_note: string;
  dpa_text: string;
}

// GET …/draft-context — builder_forms MAJOR "AI drafting lacks source
// transparency…" (n=3, ask 1).
export interface DraftContext {
  section: string;
  sources: string[];
  facts: Record<string, string>;
  excluded: string;
  provider: Omit<ProviderDisclosure, "dpa_text">;
}

// GET …/audit-record — ai_draft BLOCKER "Attestation is a button click…
// exportable audit record" (n=4).
export interface SectionAuditRecord {
  dossier_id: string;
  section: string;
  title: string;
  content_origin: string | null;
  content_confirmed: boolean;
  content_author: string | null;
  attestation: SectionNodeR9["attestation"];
  updated_at: string | null;
  draft_text: string | null;
  documents: (DocMeta & { lang?: string })[];
  events: unknown[];
  generated_at: string;
  storage: string;
}

// GET /dossiers/{id}/sections-rollup — ai_draft BLOCKER "No project-level
// roll-up" (n=2) + MAJOR "Per-leaf attestation click-tax; no bulk attest" (n=6).
export interface RollupRow {
  section: string;
  module: string;
  title: string;
  status: string;
  applicability: string;
  content_origin: string | null;
  content_confirmed: boolean;
  needs_review: boolean;
  owner: string;
  attested_by: string;
  updated_at: string;
}

export interface SectionsRollup {
  dossier_id: string;
  rows: RollupRow[];
  counts: Record<string, number>;
  review_queue: (RollupRow & { documents: (DocMeta & { lang?: string })[] })[];
  generated_at: string;
}

export const draftApi = {
  aiProvider: () => j<ProviderDisclosure>("/ai-provider"),

  draftContext: (id: string, section: string) =>
    j<DraftContext>(
      `/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/draft-context`),

  // POST …/ai-policy — builder_forms MAJOR (n=3, ask 2): per-section AI
  // off-switch for client filings (server-enforced on both draft paths).
  setAiPolicy: (id: string, section: string, disabled: boolean, reason = "") =>
    j<ContentState>(
      `/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/ai-policy`,
      { method: "POST", body: JSON.stringify({ disabled, reason }) }),

  // POST …/confirm-content with the reviewer's typed name + credential —
  // ai_draft BLOCKER (n=4): inspection-grade, identity-stamped attestation.
  confirmContentAttested: (
    id: string,
    section: string,
    attest: { attest_name: string; attest_credential?: string;
              attest_meaning?: string }
  ) =>
    j<ContentState>(
      `/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/confirm-content`,
      { method: "POST", body: JSON.stringify(attest) }),

  sectionAuditRecord: (id: string, section: string) =>
    j<SectionAuditRecord>(
      `/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/audit-record`),

  sectionsRollup: (id: string) =>
    j<SectionsRollup>(`/dossiers/${encodeURIComponent(id)}/sections-rollup`),
};
