// Client over the same-origin /api/collab proxy → the collaboration microservice.
// Portfolio-level roll-up (WS7): open tasks grouped by dossier → assignees +
// blocked status, so a CRO/CDMO PM sees the team without opening each dossier.

const BASE = "/api/collab";

export interface DossierTaskSummary {
  open: number;
  overdue: number;
  assignees: string[];
  blocked: boolean;
}

export interface TaskSummary {
  by_dossier: Record<string, DossierTaskSummary>;
}

async function j<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json() as Promise<T>;
}

export const collabApi = {
  // GET /tasks/summary — portfolio open-task roll-up by dossier.
  taskSummary: () => j<TaskSummary>(`/tasks/summary`),
};
