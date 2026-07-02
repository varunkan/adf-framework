// Server-side proxy to the dossier service. Unlike the JSON journey proxy, this
// STREAMS the raw request body and passes the incoming content-type through, so
// multipart file uploads survive; it also forwards content-type/disposition on
// responses so document downloads work.
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BFF = process.env.DOSSIER_BFF_URL || "http://127.0.0.1:8010";

async function forward(req: NextRequest, path: string[]) {
  const suffix = path.map(encodeURIComponent).join("/");
  const qs = req.nextUrl.search || "";
  const url = `${BFF}/api/dossier/${suffix}${qs}`;

  const headers: Record<string, string> = {};
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;

  const init: RequestInit & { duplex?: string } = {
    method: req.method,
    headers,
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    // raw bytes — preserves the multipart boundary
    init.body = Buffer.from(await req.arrayBuffer());
  }

  try {
    const upstream = await fetch(url, init);
    const upstreamCt = upstream.headers.get("content-type") || "";
    // SSE (interactive-drafting chat) — pipe the stream through live instead
    // of buffering, so the client sees tokens as they arrive.
    if (upstreamCt.includes("text/event-stream") && upstream.body) {
      return new NextResponse(upstream.body, {
        status: upstream.status,
        headers: {
          "content-type": upstreamCt,
          "cache-control": "no-cache",
          connection: "keep-alive",
        },
      });
    }
    const buf = Buffer.from(await upstream.arrayBuffer());
    const respHeaders: Record<string, string> = {
      "content-type": upstreamCt || "application/json",
    };
    const cd = upstream.headers.get("content-disposition");
    if (cd) respHeaders["content-disposition"] = cd;
    return new NextResponse(buf, { status: upstream.status, headers: respHeaders });
  } catch (e) {
    return NextResponse.json(
      { type: "about:blank", title: "dossier service unreachable",
        status: 503, detail: `${BFF} — ${String(e)}` },
      { status: 503 }
    );
  }
}

type Ctx = { params: { path: string[] } };
export const GET = (r: NextRequest, { params }: Ctx) => forward(r, params.path);
export const POST = (r: NextRequest, { params }: Ctx) => forward(r, params.path);
export const PUT = (r: NextRequest, { params }: Ctx) => forward(r, params.path);
export const PATCH = (r: NextRequest, { params }: Ctx) => forward(r, params.path);
export const DELETE = (r: NextRequest, { params }: Ctx) => forward(r, params.path);
