// Server-side proxy to the collab service. Gated: requires a valid session and
// (when a dossier_id is referenced in the path, query, OR JSON body) confirms
// the caller's tenant owns it — then the collab service itself also filters by
// the injected X-Tenant-Id (defense in depth).
import { NextRequest, NextResponse } from "next/server";
import { requireTenant, tenantHeaders, dossierIdFromReq, dossierIdFromBody,
         ownsDossier, notFound } from "@/lib/serverAuth";

export const dynamic = "force-dynamic";

const BFF = process.env.COLLAB_BFF_URL || "http://127.0.0.1:8018";

async function forward(req: NextRequest, path: string[]) {
  const gate = await requireTenant(req);
  if (gate instanceof NextResponse) return gate;

  // read the body ONCE (so we can both inspect + forward it)
  let bodyBuf: Buffer | null = null;
  if (req.method !== "GET" && req.method !== "HEAD") {
    bodyBuf = Buffer.from(await req.arrayBuffer());
  }
  const did =
    dossierIdFromReq(req, path) ||
    (bodyBuf ? dossierIdFromBody(bodyBuf.toString("utf8")) : null);
  if (did && !(await ownsDossier(gate, did))) return notFound(did);

  const suffix = path.map(encodeURIComponent).join("/");
  const qs = req.nextUrl.search || "";
  const url = `${BFF}/api/collab/${suffix}${qs}`;
  const headers: Record<string, string> = { ...tenantHeaders(gate) };
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;

  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (bodyBuf) init.body = new Uint8Array(bodyBuf);
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
      { type: "about:blank", title: "collaboration service unreachable",
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
