// Server-side proxy to the identity service (auth, tenancy, entitlements).
// This is the ONLY open proxy (login/signup must be reachable unauthenticated).
// On login/signup it sets the session token as an HttpOnly cookie so the token
// is never exposed to page JavaScript (XSS-safe); logout clears it.
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BFF = process.env.IDENTITY_BFF_URL || "http://127.0.0.1:8014";
const COOKIE = "ands_token";
const MAX_AGE = 12 * 3600; // matches the identity service SESSION_TTL

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
    if (upstream.ok && (route === "auth/login" || route === "auth/signup")) {
      try {
        const token = JSON.parse(buf.toString("utf8"))?.token;
        if (token)
          res.cookies.set(COOKIE, token, {
            httpOnly: true, sameSite: "lax", path: "/", maxAge: MAX_AGE,
          });
      } catch {}
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
