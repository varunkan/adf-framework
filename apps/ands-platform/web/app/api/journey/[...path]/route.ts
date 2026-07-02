// Server-side proxy: the browser talks to the Next app (same origin), which
// forwards to the journey BFF. Keeps the BFF URL server-only and sidesteps CORS
// in dev. In production the gateway (/api/journey/*) plays this role.
import { NextRequest, NextResponse } from "next/server";
import { requireTenant, tenantHeaders } from "@/lib/serverAuth";

export const dynamic = "force-dynamic";

const BFF = process.env.JOURNEY_BFF_URL || "http://127.0.0.1:8000";

async function forward(req: NextRequest, path: string[]) {
  const gate = await requireTenant(req);
  if (gate instanceof NextResponse) return gate;
  const suffix = path.join("/");
  const qs = req.nextUrl.search || "";
  const url = `${BFF}/api/journey/${suffix}${qs}`;
  const headers: Record<string, string> = {
    "content-type": "application/json", ...tenantHeaders(gate),
  };
  const init: RequestInit = {
    method: req.method,
    headers,
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }
  try {
    const upstream = await fetch(url, init);
    const text = await upstream.text();
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") || "application/json",
      },
    });
  } catch (e) {
    return NextResponse.json(
      {
        type: "about:blank",
        title: "journey service unreachable",
        status: 503,
        detail: `${BFF} — ${String(e)}`,
      },
      { status: 503 }
    );
  }
}

type Ctx = { params: { path: string[] } };
export const GET = (req: NextRequest, { params }: Ctx) =>
  forward(req, params.path);
export const POST = (req: NextRequest, { params }: Ctx) =>
  forward(req, params.path);
export const PUT = (req: NextRequest, { params }: Ctx) =>
  forward(req, params.path);
export const PATCH = (req: NextRequest, { params }: Ctx) =>
  forward(req, params.path);
export const DELETE = (req: NextRequest, { params }: Ctx) =>
  forward(req, params.path);
