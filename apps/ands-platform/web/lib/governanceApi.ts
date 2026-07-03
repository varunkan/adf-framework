// Client over the same-origin /api/governance proxy → the governance service
// (the append-only Part-11 audit trail). The proxy injects X-Tenant-Id, so
// these reads are already scoped to the caller's workspace.
export type AuditEvent = {
  id: string;
  seq: number;
  at: string;
  category: string;
  action: string;
  dossier_id: string;
  tenant_id: string;
  detail: Record<string, unknown>;
};

const BASE = "/api/governance";

export const governanceApi = {
  // Workspace-wide audit (no dossier filter) — newest first, capped.
  listAudit: async (limit = 200): Promise<AuditEvent[]> => {
    const res = await fetch(`${BASE}/audit?limit=${limit}`, {
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`governance service replied ${res.status}`);
    const body = await res.json();
    return (body.events || []) as AuditEvent[];
  },

  // The service's own PlainText inspection export (GET /audit/export).
  exportText: async (): Promise<string> => {
    const res = await fetch(`${BASE}/audit/export`, { cache: "no-store" });
    if (!res.ok) throw new Error(`governance service replied ${res.status}`);
    return res.text();
  },
};

// Turn the audit events into a downloadable CSV/JSON blob (client-side), and a
// filename, for the account audit viewer's Download button.
export function auditToCsv(events: AuditEvent[]): string {
  const esc = (s: unknown) => `"${String(s ?? "").replace(/"/g, '""')}"`;
  const rows = [
    ["seq", "at", "category", "action", "actor", "dossier_id", "tenant_id", "detail"],
    ...events.map((e) => [
      e.seq,
      e.at,
      e.category,
      e.action,
      (e.detail?.actor as string) || "",
      e.dossier_id,
      e.tenant_id,
      JSON.stringify(
        Object.fromEntries(
          Object.entries(e.detail || {}).filter(([k]) => k !== "actor")
        )
      ),
    ]),
  ];
  return rows.map((r) => r.map(esc).join(",")).join("\n");
}

export function download(name: string, body: string, type: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([body], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
