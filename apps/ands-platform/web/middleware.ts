// Session gate: every page requires the `ands_token` cookie except /login.
// API proxies pass through — the services enforce tenancy via the headers the
// proxies inject; pages are gated here so an unauthenticated visit lands on
// the sign-in screen with a `next` return path.
import { NextRequest, NextResponse } from "next/server";

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (
    pathname.startsWith("/api") ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/login") ||
    // CAMP-SSO-OIDC: the OIDC redirect_uri landing page runs BEFORE a session
    // exists (it is what mints the session), so it must be reachable unauthed.
    pathname.startsWith("/auth/sso/callback") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }
  if (!req.cookies.get("ands_token")?.value) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
