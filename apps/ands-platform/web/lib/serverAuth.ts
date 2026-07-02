// Server-side (proxy route) session resolution: token cookie -> principal via
// the identity service, with a short in-memory cache so every dossier/journey
// proxy hop doesn't re-hit identity.
import type { NextRequest } from "next/server";

const IDENTITY = process.env.IDENTITY_BFF_URL || "http://127.0.0.1:8014";
const TTL_MS = 30_000;

type Cached = { tenantId: string; email: string; exp: number };
const cache = new Map<string, Cached>();

export async function resolveTenant(
  req: NextRequest
): Promise<{ tenantId: string; token: string } | null> {
  const token = req.cookies.get("ands_token")?.value || "";
  if (!token) return null;
  const hit = cache.get(token);
  if (hit && hit.exp > Date.now()) return { tenantId: hit.tenantId, token };
  try {
    const r = await fetch(`${IDENTITY}/api/identity/auth/me`, {
      headers: { authorization: `Bearer ${token}` },
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
    cache.set(token, {
      tenantId,
      email: me?.email || "",
      exp: Date.now() + TTL_MS,
    });
    return { tenantId, token };
  } catch {
    return null;   // identity down — degrade to unscoped (dev-tier behavior)
  }
}
