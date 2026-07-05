// Client-side auth over the /api/identity proxy. The session token lives in
// a cookie (`ands_token`) so Next middleware can gate pages AND the server
// proxies can resolve the tenant for scoping.

// /auth/me returns a FLAT principal
import { friendlyError } from "./friendlyError";
export interface Principal {
  user_id: string;
  tenant_id: string;
  role: string;
  email: string;
  name?: string;         // display name from the account record
  tenant_name?: string;  // workspace name — server-side, not a browser cache
  // CAMP-SSO-OIDC: whether this principal is an IdP-VERIFIED identity (signed in
  // via the workspace's OIDC provider) vs a recorded email (password login).
  identity_verified?: boolean;
  identity_issuer?: string;
  identity_subject?: string;
}

// CAMP-SSO-OIDC: per-workspace SSO (OpenID Connect) configuration.
export interface SsoConfig {
  tenant_id: string;
  enabled: boolean;
  issuer: string;
  client_id: string;
  redirect_uri: string;
  has_secret: boolean;   // whether a client secret is stored (never the secret)
  configured: boolean;
  can_manage: boolean;
  protocol: string;
}

export interface RoleMatrixRow {
  role: string;
  label: string;
  summary: string;
  capabilities: string[];
  assignable_by: string;
}

export interface TenantSecurity {
  tenant_id: string;
  require_mfa: boolean;
  // TIER3-SOD-ENFORCE: when true, a signer-is-author e-signature is HARD-BLOCKED
  // on the sign path (server-enforced by the dossier service), not just warned.
  require_sod: boolean;
  can_manage: boolean;
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
    throw new Error(friendlyError(res.status, detail));
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
  login: async (email: string, password: string, mfaCode = "") => {
    const r = await j<{ user: any; token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, mfa_code: mfaCode }),
    });
    return r;
  },
  me: () => j<Principal>("/auth/me"),
  mfa: {
    status: () => j<{ enabled: boolean }>("/auth/mfa/status"),
    enroll: () =>
      j<{ secret: string; provisioning_uri: string }>("/auth/mfa/enroll",
        { method: "POST" }),
    verify: (code: string) =>
      j<{ enabled: boolean }>("/auth/mfa/verify",
        { method: "POST", body: JSON.stringify({ code }) }),
  },
  // CAMP-SSO-OIDC: standards-based SSO (OpenID Connect Authorization Code + PKCE)
  sso: {
    // read the workspace SSO config (secret never returned — only has_secret)
    get: () => j<SsoConfig>("/tenant/sso"),
    // admin-only: enable + set issuer / client_id (+ optional secret/redirect)
    set: (cfg: { enabled: boolean; issuer: string; client_id: string;
                 client_secret?: string; redirect_uri?: string }) =>
      j<SsoConfig>("/tenant/sso",
        { method: "POST", body: JSON.stringify(cfg) }),
    // begin an OIDC login: get the IdP authorization redirect + opaque state
    authorize: (tenant_id: string, redirect_uri: string) =>
      j<{ authorization_url: string; state: string }>(
        "/auth/sso/authorize",
        { method: "POST",
          body: JSON.stringify({ tenant_id, redirect_uri }) }),
    // complete the login after the IdP redirects back with code + state
    callback: (state: string, code: string) =>
      j<{ user: any; token: string;
          identity: { verified: boolean; issuer: string; subject: string } }>(
        "/auth/sso/callback",
        { method: "POST", body: JSON.stringify({ state, code }) }),
  },
  roleMatrix: () => j<{ roles: RoleMatrixRow[] }>("/rbac/matrix"),
  tenantSecurity: () => j<TenantSecurity>("/tenant/security"),
  setRequireMfa: (require_mfa: boolean) =>
    j<{ tenant_id: string; require_mfa: boolean }>(
      "/tenant/security/require-mfa",
      { method: "POST", body: JSON.stringify({ require_mfa }) }),
  // TIER3-SOD-ENFORCE: flip the per-workspace 'enforce segregation of duties'
  // policy. Enforcement lives server-side on the sign path — this only records
  // the workspace's intent.
  setRequireSod: (require_sod: boolean) =>
    j<{ tenant_id: string; require_sod: boolean }>(
      "/tenant/security/require-sod",
      { method: "POST", body: JSON.stringify({ require_sod }) }),
  resetRequest: (email: string) =>
    j<{ ok: boolean; message: string; reset_code?: string; delivery?: string }>(
      "/auth/reset/request",
      { method: "POST", body: JSON.stringify({ email }) }),
  resetComplete: (email: string, code: string, newPassword: string) =>
    j<{ ok: boolean; accounts_updated: number }>(
      "/auth/reset/complete",
      { method: "POST",
        body: JSON.stringify({ email, code, new_password: newPassword }) }),
  logout: async () => {
    try { await j("/auth/logout", { method: "POST" }); } catch {}
    try { localStorage.removeItem(TENANT_NAME_KEY); } catch {}
  },
};
