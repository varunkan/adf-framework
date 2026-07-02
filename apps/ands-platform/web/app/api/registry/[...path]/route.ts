// Server-side proxy to the registry service (registrations, DIN, RTS).
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BFF = process.env.REGISTRY_BFF_URL || "http://127.0.0.1:8016";

async function forward(req: NextRequest, path: string[]) {
  const suffix = path.map(encodeURIComponent).join("/");
  const qs = req.nextUrl.search || "";
  const url = `${BFF}/api/registry/${suffix}${qs}`;

  const headers: Record<string, string> = {};
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  // Authorization from the header or the session cookie (browser fetches)
  const auth =
    req.headers.get("authorization") ||
    (req.cookies.get("ands_token")?.value
      ? `Bearer ${req.cookies.get("ands_token")!.value}`
      : "");
  if (auth) headers["authorization"] = auth;

  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = Buffer.from(await req.arrayBuffer());
  }
  try {
    const upstream = await fetch(url, init);
    const buf = Buffer.from(await upstream.arrayBuffer());
    return new NextResponse(buf, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") || "application/json",
      },
    });
  } catch (e) {
    return NextResponse.json(
      { type: "about:blank", title: "registry service unreachable",
        status: 503, detail: `${BFF} — ${String(e)}` },
      { status: 503 }
    );
  }
}

type Ctx = { params: { path: string[] } };
export const GET = (r: NextRequest, { params }: Ctx) => forward(r, params.path);
export const POST = (r: NextRequest, { params }: Ctx) => forward(r, params.path);
