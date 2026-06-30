// Thin client over the same-origin /api/journey proxy (-> the journey BFF).
import type { Catalog, IntakeAssessment, JourneyView } from "./types";

const BASE = "/api/journey";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || body.title || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  catalog: () => j<Catalog>("/catalog"),

  start: (body: { title?: string; tenant_id?: string; answers?: any }) =>
    j<JourneyView>("/start", { method: "POST", body: JSON.stringify(body) }),

  get: (id: string) => j<JourneyView>(`/${id}`),

  advance: (id: string, step: string, data: Record<string, any> = {}) =>
    j<JourneyView>(`/${id}/advance`, {
      method: "POST",
      body: JSON.stringify({ step, data }),
    }),

  intake: (answers: Record<string, any>, session_id?: string) =>
    j<{ assessment: IntakeAssessment; view: JourneyView | null }>("/intake", {
      method: "POST",
      body: JSON.stringify({ ...answers, session_id: session_id || "" }),
    }),

  assessDossierId: (body: Record<string, any>) =>
    j<any>("/dossier-id/assess", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

// session id persistence so a returning user resumes exactly where they were
const KEY = "ands-journey-session";
export const session = {
  save: (id: string) => {
    try {
      localStorage.setItem(KEY, id);
    } catch {}
  },
  load: (): string | null => {
    try {
      return localStorage.getItem(KEY);
    } catch {
      return null;
    }
  },
  clear: () => {
    try {
      localStorage.removeItem(KEY);
    } catch {}
  },
};
