// Client over the same-origin /api/lifecycle proxy → the lifecycle service.
// Covers the HC correspondence hub (REQ-112), notice ingestion (REQ-096)
// and the Form V / NOA register (PM(NOC) Regulations).

export type CorrespondenceRecord = {
  id: string;
  dossier_id: string;
  kind: string;
  kind_label: string;
  subject: string;
  body: string | null;
  direction: "inbound" | "outbound";
  received_at: string | null;
  reference: string | null;
  created_at: string;
  // round-9: the actual HC notice document, stored with the record
  has_attachment?: boolean;
  attachment_filename?: string | null;
  attachment_sha256?: string | null;
};

export type LifecycleState = {
  dossier_id: string;
  submission_type: string;
  phase: string;
  status: string;
  decision?: string | null;
  [k: string]: any;
};

export type NoticeResult = {
  state: LifecycleState;
  correspondence: CorrespondenceRecord;
  response: { action?: string; window_days?: number; label?: string };
};

export type NoaRecord = {
  id: string;
  dossier_id: string;
  patent_number: string;
  allegation: string;
  allegation_label: string;
  form_v_date: string;
  noa_required: boolean;
  status:
    | "draft"
    | "served"
    | "action_commenced"
    | "clear"
    | "stay_running"
    | "resolved";
  served_date: string | null;
  action_window_end: string | null;
  action_date: string | null;
  court_file: string | null;
  stay_start: string | null;
  stay_end: string | null;
  resolved_at: string | null;
  outcome: string | null;
  history: { event: string; at: string }[];
  // computed clocks (with_clocks) on list reads
  as_of?: string;
  action_days_remaining?: number | null;
  stay_days_remaining?: number | null;
};

// Round-9 (operations, n=4): a manual verified-date override for one
// calculated clock — who verified, when, against which external source.
export type VerifiedDate = {
  id: string;
  dossier_id: string;
  clock_key: string;
  verified_date: string;
  calculated_date: string | null;
  source_ref: string;
  verified_by: string | null;
  verified_at: string;
  discrepancy: boolean;
  history_count?: number;
};

// Correspondence kinds, mirrored from the service's correspondence.KINDS
export const KINDS: Record<string, string> = {
  SDN: "Screening Deficiency Notice",
  SAL: "Screening Acceptance Letter",
  SRL: "Screening Rejection Letter",
  NOD: "Notice of Deficiency",
  NON: "Notice of Non-compliance",
  NOC: "Notice of Compliance",
  clarifax: "Clarification request (clarifax)",
  query: "Review query",
  commitment: "Post-NOC commitment",
  letter: "General correspondence",
};

// HC notices the DSTS state machine ingests (REQ-096)
export const NOTICES = ["SAL", "SDN", "SRL", "NOC", "NOD", "NON"] as const;

// Form V allegation types, mirrored from noa.ALLEGATIONS
export const ALLEGATIONS: Record<string, string> = {
  not_infringed: "Non-infringement (s.5(1)(b)(iv))",
  invalid: "Patent/CSP invalid or void",
  accept_expiry: "NOC to issue only on patent/CSP expiry",
  no_claim: "No claim addressed by the submission",
};

const BASE = "/api/lifecycle";

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
      // problem+json: title + detail, plus per-rule validation errors
      const rules = Array.isArray(b.errors)
        ? b.errors.map((e: any) => e.message || e.rule).join("; ")
        : "";
      detail =
        [b.title, b.detail, rules].filter(Boolean).join(": ") || detail;
    } catch {}
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<T>;
}

export const lifecycleApi = {
  state: (dossierId: string) =>
    j<LifecycleState>(`/state/${encodeURIComponent(dossierId)}`),

  start: (body: {
    dossier_id: string;
    submission_type?: string;
    received_date: string;
  }) => j<LifecycleState>("/start", { method: "POST", body: JSON.stringify(body) }),

  listCorrespondence: (dossierId: string, kind = "") =>
    j<{ correspondence: CorrespondenceRecord[]; count: number }>(
      `/correspondence?dossier_id=${encodeURIComponent(dossierId)}` +
        (kind ? `&kind=${encodeURIComponent(kind)}` : "")
    ),

  attachDocument: (cid: string, filename: string, contentType: string,
    dataBase64: string) =>
    j<{ sha256: string; filename: string }>(
      `/correspondence/${encodeURIComponent(cid)}/attachment`,
      { method: "POST",
        body: JSON.stringify({ filename, content_type: contentType,
                               data_base64: dataBase64 }) }),

  getDocument: (cid: string) =>
    j<{ filename: string; content_type: string; data_base64: string;
        sha256: string }>(
      `/correspondence/${encodeURIComponent(cid)}/attachment`),

  logCorrespondence: (body: {
    dossier_id: string;
    kind: string;
    subject: string;
    body?: string;
    direction?: string;
    received_at?: string;
    reference?: string;
  }) =>
    j<CorrespondenceRecord>("/correspondence", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  ingestNotice: (body: {
    dossier_id: string;
    notice: string;
    date: string;
    subject?: string;
    reference?: string;
  }) => j<NoticeResult>("/notice", { method: "POST", body: JSON.stringify(body) }),

  // round-9 (n=4): verified-date overrides — append-only reconciliation
  // records against the external source of truth (HC letter, Vault RIM…)
  listVerifiedDates: (dossierId: string) =>
    j<{ verifications: VerifiedDate[]; count: number }>(
      `/verified-dates?dossier_id=${encodeURIComponent(dossierId)}`),

  setVerifiedDate: (body: {
    dossier_id: string;
    clock_key: string;
    verified_date: string;
    calculated_date?: string;
    source_ref: string;
  }) =>
    j<VerifiedDate>("/verified-date", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listNoa: (dossierId: string, asOf = "") =>
    j<{ allegations: NoaRecord[]; count: number }>(
      `/noa?dossier_id=${encodeURIComponent(dossierId)}` +
        (asOf ? `&as_of=${encodeURIComponent(asOf)}` : "")
    ),

  createNoa: (body: {
    dossier_id: string;
    patent_number: string;
    allegation: string;
    form_v_date: string;
  }) => j<NoaRecord>("/noa", { method: "POST", body: JSON.stringify(body) }),

  serveNoa: (noaId: string, servedDate: string) =>
    j<NoaRecord>(`/noa/${encodeURIComponent(noaId)}/serve`, {
      method: "POST",
      body: JSON.stringify({ served_date: servedDate }),
    }),

  actionNoa: (noaId: string, actionDate: string, courtFile = "") =>
    j<NoaRecord>(`/noa/${encodeURIComponent(noaId)}/action`, {
      method: "POST",
      body: JSON.stringify({ action_date: actionDate, court_file: courtFile }),
    }),
};

export const today = () => new Date().toISOString().slice(0, 10);
