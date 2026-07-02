// Thin client over the same-origin /api/journey proxy (-> the journey BFF).
import type {
  Catalog,
  IntakeAssessment,
  JourneyView,
  TrackSummary,
} from "./types";

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
      // problem+json: title is the human-readable part; append detail only
      // when it adds information (it's often just a step/field keyword)
      const title = body.title || "";
      const extra = body.detail && body.detail !== title ? body.detail : "";
      detail =
        title && extra && !title.includes(extra)
          ? `${title}: ${extra}`
          : title || extra || detail;
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

  placeDoc: (id: string, slot_key: string, doc: string, languages?: string[]) =>
    j<JourneyView>(`/${id}/content/place`, {
      method: "POST",
      body: JSON.stringify({ slot_key, doc, languages: languages ?? null }),
    }),

  logNotice: (id: string, type: string, date: string) =>
    j<JourneyView>(`/${id}/track/notice`, {
      method: "POST",
      body: JSON.stringify({ type, date }),
    }),

  pauseClock: (id: string, type: string, paused: boolean) =>
    j<any>(`/${id}/track/pause`, {
      method: "POST",
      body: JSON.stringify({ type, paused }),
    }),

  track: (id: string, as_of: string) =>
    j<TrackSummary>(`/${id}/track?as_of=${encodeURIComponent(as_of)}`),
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
