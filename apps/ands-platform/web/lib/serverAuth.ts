// Server-side (proxy route) session resolution + auth gate. Token cookie ->
// principal via the identity service, with a short in-memory cache so every
// dossier/journey proxy hop doesn't re-hit identity.
//
// EVERY workspace-data proxy MUST call requireTenant() and 401 when it returns
// null — without this the services are reachable unauthenticated (the CRO
// tenant-isolation blocker). Only the identity proxy (login/signup) stays open.
import { NextRequest, NextResponse } from "next/server";

const IDENTITY = process.env.IDENTITY_BFF_URL || "http://127.0.0.1:8014";
const TTL_MS = 30_000;

/** Shared secret proving a request came through this proxy (not a direct hit
 *  on a backend port). Sent on every server→service call; the services gate on
 *  it when ANDS_INTERNAL_TOKEN is set. Server-only env — never sent to the browser. */
export const INTERNAL_TOKEN = process.env.ANDS_INTERNAL_TOKEN || "";
export function internalHeader(): Record<string, string> {
  return INTERNAL_TOKEN ? { "x-internal-auth": INTERNAL_TOKEN } : {};
}

export interface Session {
  tenantId: string;
  token: string;
  email: string;
}

type Cached = { tenantId: string; email: string; exp: number };
const cache = new Map<string, Cached>();

export async function resolveTenant(req: NextRequest): Promise<Session | null> {
  const token = req.cookies.get("ands_token")?.value || "";
  if (!token) return null;
  const hit = cache.get(token);
  if (hit && hit.exp > Date.now())
    return { tenantId: hit.tenantId, token, email: hit.email };
  try {
    const r = await fetch(`${IDENTITY}/api/identity/auth/me`, {
      headers: { authorization: `Bearer ${token}`, ...internalHeader() },
      cache: "no-store",
    });
    if (!r.ok) {
      cache.delete(token);
      return null;
    }
    const me = await r.json();
    // /auth/me returns a FLAT principal: {user_id, tenant_id, role, email}
    const tenantId = me?.tenant_id || "";
    if (!tenantId) return null;
    const email = me?.email || "";
    cache.set(token, { tenantId, email, exp: Date.now() + TTL_MS });
    return { tenantId, token, email };
  } catch {
    return null;
  }
}

/** A 401 problem+json for an unauthenticated proxy request. */
export function unauthorized(): NextResponse {
  return NextResponse.json(
    { type: "about:blank", title: "authentication required", status: 401,
      detail: "sign in to access this workspace" },
    { status: 401 }
  );
}

/**
 * Gate + resolve in one call: returns the session, or throws a Response the
 * proxy should return directly. Proxies use:
 *   const gate = await requireTenant(req);
 *   if (gate instanceof NextResponse) return gate;
 */
export async function requireTenant(
  req: NextRequest
): Promise<Session | NextResponse> {
  const session = await resolveTenant(req);
  return session ?? unauthorized();
}

/** Headers every downstream service call should carry once authenticated. */
export function tenantHeaders(s: Session): Record<string, string> {
  return {
    "x-tenant-id": s.tenantId,
    "x-user-email": s.email,
    authorization: `Bearer ${s.token}`,
    ...internalHeader(),
  };
}

const DOSSIER = process.env.DOSSIER_BFF_URL || "http://127.0.0.1:8010";
const DID_RE = /^[a-z]\d{6,7}$/;

/** Pull a dossier id out of a proxied path or ?dossier_id= query. */
export function dossierIdFromReq(
  req: NextRequest,
  path: string[]
): string | null {
  for (const seg of path) {
    const s = decodeURIComponent(seg);
    if (DID_RE.test(s)) return s;
  }
  const q = req.nextUrl.searchParams.get("dossier_id");
  return q && DID_RE.test(q) ? q : null;
}

/** dossier_id carried in a JSON body (write routes) — the proxy can't see it
 *  in the path/query, so writes like create-NOA/report-shortage/submit would
 *  otherwise escape the ownership check. Parses a pre-read body buffer. */
export function dossierIdFromBody(bodyText: string): string | null {
  try {
    const b = JSON.parse(bodyText);
    const v = b?.dossier_id;
    return typeof v === "string" && DID_RE.test(v) ? v : null;
  } catch {
    return null;
  }
}

/**
 * The dossier service is the ownership authority: ancillary services
 * (governance/registry/lifecycle/collab) key on dossier_id with no tenant
 * column, so a proxy for them confirms the caller owns the referenced dossier
 * by asking the dossier service (which 404s cross-tenant). Fail-closed.
 */
export async function ownsDossier(s: Session, dossierId: string): Promise<boolean> {
  try {
    const r = await fetch(
      `${DOSSIER}/api/dossier/dossiers/${encodeURIComponent(dossierId)}`,
      { headers: { "x-tenant-id": s.tenantId, ...internalHeader() },
        cache: "no-store" }
    );
    return r.ok;
  } catch {
    return false;
  }
}

export function notFound(detail: string): NextResponse {
  return NextResponse.json(
    { type: "about:blank", title: "no such dossier", status: 404, detail },
    { status: 404 }
  );
}
