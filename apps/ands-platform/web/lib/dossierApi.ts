// Client over the same-origin /api/dossier proxy → the dossier microservice.
import { friendlyError } from "./friendlyError";
import type {
  ContentState,
  DossierFull,
  DossierListItem,
  ExportOutcome,
  OutlineView,
  SequenceList,
  ValidationResult,
  ValidationRuleCatalog,
} from "./dossierTypes";

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
      // problem+json: title is the human-readable part, detail the specifics
      detail = [b.title, b.detail].filter(Boolean).join(": ") || detail;
    } catch {}
    throw new Error(friendlyError(res.status, detail));
  }
  return res.json() as Promise<T>;
}

export const dossierApi = {
  listDossiers: () =>
    j<{ dossiers: DossierListItem[]; count: number }>("/dossiers"),

  createDossier: (body: {
    dossier_id: string;
    title?: string;
    submission_type?: string;
    cs_be_only?: boolean;
  }) => j<any>("/dossiers", { method: "POST", body: JSON.stringify(body) }),

  getDossier: (id: string) => j<DossierFull>(`/dossiers/${encodeURIComponent(id)}`),

  deleteDossier: (id: string) =>
    j<{ deleted: string }>(`/dossiers/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  // placeholder ID -> real Health Canada Dossier ID (issued via REP)
  renameDossier: (id: string, newId: string) =>
    j<{ renamed: string; dossier_id: string }>(
      `/dossiers/${encodeURIComponent(id)}/rename`,
      { method: "POST", body: JSON.stringify({ new_id: newId }) }),

  getContent: (id: string) =>
    j<ContentState>(`/dossiers/${encodeURIComponent(id)}/content`),

  generate: (id: string, section: string, payload: Record<string, any> = {}) =>
    j<ContentState>(
      `/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/generate`,
      { method: "POST", body: JSON.stringify(payload) }
    ),

  // realistic, editable pre-fill for an authorable form
  formSample: (id: string, section: string) =>
    j<{ section: string; generator_key: string;
        fields: Record<string, string>; sample_keys: string[] }>(
      `/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/sample`),

  // Health Canada content review of the form's fields
  formReview: (id: string, section: string, fields: Record<string, any>) =>
    j<{ section: string; generator_key: string; passed: boolean;
        error_count: number; warning_count: number; guidance_url: string;
        findings: { severity: string; rule: string; message: string;
                    hc_url: string; suggested_edit: string }[] }>(
      `/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/review`,
      { method: "POST", body: JSON.stringify(fields) }),

  // WS2: the explicit "I have reviewed and edited this — it is my content"
  // action that clears the sample/AI review block (recorded to the audit trail).
  confirmContent: (id: string, section: string) =>
    j<ContentState>(
      `/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/confirm-content`,
      { method: "POST", body: JSON.stringify({}) }
    ),

  markNa: (id: string, section: string, reason: string) =>
    j<ContentState>(
      `/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/mark-na`,
      { method: "POST", body: JSON.stringify({ reason }) }
    ),

  setFees: (id: string, fee_paid: boolean, sme_granted: boolean) =>
    j<ContentState>(`/dossiers/${encodeURIComponent(id)}/fees`, {
      method: "POST",
      body: JSON.stringify({ fee_paid, sme_granted }),
    }),

  validate: (id: string) =>
    j<ValidationResult>(`/dossiers/${encodeURIComponent(id)}/validate`),

  // The queryable registry of every structural/technical rule + the honest
  // criteria block. Powers the "what do we actually check" surface.
  validationRules: () =>
    j<ValidationRuleCatalog>(`/validation/rules`),

  outline: (id: string, sequence = "0000") =>
    j<OutlineView>(
      `/ectd/${encodeURIComponent(id)}/viewer/outline/${encodeURIComponent(sequence)}`
    ),

  documentUrl: (docId: string) => `${BASE}/documents/${encodeURIComponent(docId)}`,

  // Working sequences (0001+) — the regulatory-response lifecycle.
  listSequences: (id: string) =>
    j<SequenceList>(`/dossiers/${encodeURIComponent(id)}/sequences`),

  createSequence: (
    id: string,
    body: { sequence: string; purpose?: string; note?: string }
  ) =>
    j<SequenceList>(`/dossiers/${encodeURIComponent(id)}/sequences`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  activateSequence: (id: string, sequence: string) =>
    j<SequenceList>(
      `/dossiers/${encodeURIComponent(id)}/sequences/${encodeURIComponent(sequence)}/activate`,
      { method: "POST" }
    ),

  // (Removed exportUrl — a bare export URL is a silent-download footgun that
  // would bypass the fail-closed validation gate. All export goes through
  // exportSequence below, which surfaces the 409 block.)

  // Export the transmissible package. The backend FAILS CLOSED: without a
  // valid, passing validation it returns 409 with the blocking findings +
  // criteria instead of a package. So we cannot use a bare browser download —
  // we fetch, and:
  //   - on 2xx: return the package Blob (+ X-Export-Validation stamp) so the
  //     caller can trigger a real download.
  //   - on 409: return the parsed verdict so the UI can show the blocking
  //     findings and offer an explicit override (below).
  // Pass { override:true, reason } to override a failed validation; the backend
  // records the reason to the audit trail. A 422 override_reason_required comes
  // back if the reason is blank (surfaced as a normal block outcome).
  exportSequence: async (
    id: string,
    sequence: string,
    opts: { override?: boolean; reason?: string } = {}
  ): Promise<ExportOutcome> => {
    const params = new URLSearchParams();
    if (opts.override) params.set("override", "true");
    if (opts.reason) params.set("reason", opts.reason);
    const qs = params.toString();
    const url =
      `${BASE}/ectd/${encodeURIComponent(id)}/export/${encodeURIComponent(sequence)}` +
      (qs ? `?${qs}` : "");
    const res = await fetch(url, { cache: "no-store" });
    if (res.ok) {
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") || "";
      const m = /filename="?([^"]+)"?/.exec(cd);
      return {
        ok: true,
        blob,
        filename: m?.[1] || `${id}-${sequence}.zip`,
        stamp: (res.headers.get("X-Export-Validation") as
          | "passed"
          | "overridden"
          | "unknown"
          | null) || null,
      };
    }
    // problem+json — carries { title, detail, validation:{...} } on the gate
    let body: any = {};
    try {
      body = await res.json();
    } catch {}
    return {
      ok: false,
      status: res.status,
      title: body.title || `${res.status}`,
      detail: body.detail,
      validation: body.validation,
    };
  },

  buildPmXml: (body: { dossier_id: string; lang: string; product_name: string;
                       din?: string; sections: { code: string; title: string;
                       text: string }[] }) =>
    j<{ xml: string; validation: { valid: boolean; blocking: boolean;
        findings: { rule: string; severity: string; message: string }[] } }>(
      "/monograph/xml/build", { method: "POST", body: JSON.stringify(body) }),

  // Interactive (LLM chat) drafting — streams { delta } / { error } chunks
  // parsed out of the upstream SSE response.
  streamDraftChat: async function* (
    id: string,
    section: string,
    messages: { role: string; content: string }[]
  ): AsyncGenerator<{ delta?: string; error?: string }> {
    const res = await fetch(
      `${BASE}/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/draft-chat`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages }),
        cache: "no-store",
      }
    );
    if (!res.ok || !res.body) {
      let detail = `${res.status}`;
      try {
        const b = await res.json();
        detail = [b.title, b.detail].filter(Boolean).join(": ") || detail;
      } catch {}
      throw new Error(friendlyError(res.status, detail));
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const events = buf.split("\n\n");
      buf = events.pop() || "";
      for (const evt of events) {
        const line = evt.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const raw = line.slice(6);
        if (raw === "[DONE]") return;
        try {
          yield JSON.parse(raw);
        } catch {}
      }
    }
  },

  // Multipart upload via XHR so we get real upload progress.
  uploadDocument: (
    id: string,
    section: string,
    file: File,
    opts: { lang?: string; onProgress?: (pct: number) => void } = {}
  ): Promise<ContentState> =>
    new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      if (opts.lang) form.append("lang", opts.lang);
      const xhr = new XMLHttpRequest();
      xhr.open(
        "POST",
        `${BASE}/ectd/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}/upload`
      );
      if (xhr.upload && opts.onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) opts.onProgress!(Math.round((e.loaded / e.total) * 100));
        };
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (e) {
            reject(new Error("bad response"));
          }
        } else {
          let detail = `${xhr.status}`;
          try {
            const b = JSON.parse(xhr.responseText);
            detail = [b.title, b.detail].filter(Boolean).join(": ") || detail;
          } catch {}
          reject(new Error(detail));
        }
      };
      xhr.onerror = () => reject(new Error("network error"));
      xhr.send(form);
    }),
};
