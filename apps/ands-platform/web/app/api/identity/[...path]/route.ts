// Server-side proxy to the identity service (auth, tenancy, entitlements).
// This is the ONLY open proxy (login/signup must be reachable unauthenticated).
// On login/signup it sets the session token as an HttpOnly cookie so the token
// is never exposed to page JavaScript (XSS-safe); logout clears it.
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BFF = process.env.IDENTITY_BFF_URL || "http://127.0.0.1:8014";
const COOKIE = "ands_token";
// Cookie lifetime MUST match the identity service SESSION_TTL (default 7 days,
// env ANDS_SESSION_TTL_HOURS). A 12h cookie/session logged active users out
// mid-work; the cookie is now re-issued on every successful auth/me (rolling
// window) so it tracks the server-side sliding session renewal.
const MAX_AGE = Number(process.env.ANDS_SESSION_TTL_HOURS || "168") * 3600;
const COOKIE_OPTS = {
  httpOnly: true, sameSite: "lax" as const, path: "/", maxAge: MAX_AGE,
};

async function forward(req: NextRequest, path: string[]) {
  const suffix = path.map(encodeURIComponent).join("/");
  const qs = req.nextUrl.search || "";
  const url = `${BFF}/api/identity/${suffix}${qs}`;

  const headers: Record<string, string> = {};
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  const auth =
    req.headers.get("authorization") ||
    (req.cookies.get(COOKIE)?.value
      ? `Bearer ${req.cookies.get(COOKIE)!.value}`
      : "");
  if (auth) headers["authorization"] = auth;
  // prove the request came through this proxy (identity gates on it too)
  if (process.env.ANDS_INTERNAL_TOKEN)
    headers["x-internal-auth"] = process.env.ANDS_INTERNAL_TOKEN;

  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = Buffer.from(await req.arrayBuffer());
  }
  try {
    const upstream = await fetch(url, init);
    const buf = Buffer.from(await upstream.arrayBuffer());
    const res = new NextResponse(buf, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") || "application/json",
      },
    });
    const route = path.join("/");
    // set the HttpOnly session cookie from a successful auth response
    // (CAMP-SSO-OIDC: the SSO callback mints a session token exactly like a
    // password login, so the same cookie is set here).
    if (
      upstream.ok &&
      (route === "auth/login" ||
        route === "auth/signup" ||
        route === "auth/sso/callback")
    ) {
      try {
        const token = JSON.parse(buf.toString("utf8"))?.token;
        if (token) res.cookies.set(COOKIE, token, COOKIE_OPTS);
      } catch {}
    } else if (upstream.ok && route === "auth/me") {
      // Rolling cookie: a live session (the identity service just slid its
      // expiry forward) → re-issue the SAME token with a fresh max-age so the
      // browser cookie never expires out from under an active user and bounces
      // them to /login.
      const existing = req.cookies.get(COOKIE)?.value;
      if (existing) res.cookies.set(COOKIE, existing, COOKIE_OPTS);
    }
    if (route === "auth/logout") res.cookies.delete(COOKIE);
    return res;
  } catch (e) {
    return NextResponse.json(
      { type: "about:blank", title: "identity service unreachable",
        status: 503, detail: `${BFF} — ${String(e)}` },
      { status: 503 }
    );
  }
}

type Ctx = { params: { path: string[] } };
export const GET = (r: NextRequest, { params }: Ctx) => forward(r, params.path);
export const POST = (r: NextRequest, { params }: Ctx) => forward(r, params.path);
