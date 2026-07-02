// Client-side auth over the /api/identity proxy. The session token lives in
// a cookie (`ands_token`) so Next middleware can gate pages AND the server
// proxies can resolve the tenant for scoping.

// /auth/me returns a FLAT principal
export interface Principal {
  user_id: string;
  tenant_id: string;
  role: string;
  email: string;
}

const TENANT_NAME_KEY = "ands_tenant_name";
export function tenantName(): string {
  try { return localStorage.getItem(TENANT_NAME_KEY) || ""; } catch { return ""; }
}

// The session token lives in an HttpOnly cookie set by the /api/identity proxy
// on login/signup — page JS never sees it (XSS-safe). Only the non-sensitive
// tenant name is kept client-side for the header chip.
async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/identity${path}`, {
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
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const auth = {
  signup: async (email: string, password: string, company: string) => {
    const r = await j<{ tenant: any; user: any; token: string }>(
      "/auth/signup", {
        method: "POST",
        body: JSON.stringify({ email, password, company_name: company }),
      });
    // the proxy set the HttpOnly cookie; just remember the display name
    try {
      localStorage.setItem(TENANT_NAME_KEY, r.tenant?.name || company || "");
    } catch {}
    return r;
  },
  login: async (email: string, password: string) => {
    const r = await j<{ user: any; token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    return r;
  },
  me: () => j<Principal>("/auth/me"),
  logout: async () => {
    try { await j("/auth/logout", { method: "POST" }); } catch {}
    try { localStorage.removeItem(TENANT_NAME_KEY); } catch {}
  },
};
