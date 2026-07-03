// Client over the same-origin /api/lifecycle proxy → the lifecycle microservice.
// Surfaces the DSTS submission lifecycle (WS7): submission type + service
// standard, and — for a screening/deficiency notice — the SDN/NOD response path
// with its statutory clock. Every value here comes from the lifecycle service;
// nothing is hardcoded status.

const BASE = "/api/lifecycle";

// A statutory-holiday-aware deadline timer the lifecycle state machine attaches
// to a screening target / SDN / NOD / review window.
export interface LifecycleTimer {
  kind: string; // "screening_target" | "review" | "SDN" | "NOD" | "NON"
  days: number;
  start: string;
  due: string;
  basis: string;
  adjusted: boolean;
  status: string;
}

// The DSTS lifecycle state (GET /state/{dossier_id}).
export interface LifecycleState {
  dossier_id: string;
  submission_type: string;
  phase: string; // Screening | Review | Complete
  status: string; // Active | Inactive-45 | Inactive-90 | Screening-Rejected | …
  received_at: string;
  review_started_at: string | null;
  screening_outcome: string | null; // SAL | SDN | SRL
  decision: string | null; // NOC | NOD | NON
  decided_at: string | null;
  screening_due: string | null;
  review_due: string | null;
  fee_credit: Record<string, unknown> | null;
  timers: LifecycleTimer[];
  history: { event: string; at?: string; reason?: string }[];
}

// The service standard for a submission type (GET /service-standard).
export interface ServiceStandard {
  submission_type: string;
  review_target_days: number;
  on_time_pct: number;
  label: string;
}

async function j<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const b = await res.json();
      detail = [b.title, b.detail].filter(Boolean).join(": ") || detail;
    } catch {}
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<T>;
}

export const lifecycleApi = {
  // The lifecycle may not have been started for a dossier yet → 404. Callers
  // treat that as "no HC lifecycle activity yet", not an error.
  state: (dossierId: string) =>
    j<LifecycleState>(`/state/${encodeURIComponent(dossierId)}`),

  serviceStandard: (submissionType: string) =>
    j<ServiceStandard>(
      `/service-standard?submission_type=${encodeURIComponent(submissionType)}`
    ),
};
