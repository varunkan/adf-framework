// Server-side proxy to the lifecycle service. Gated: requires a valid session and
// (when a dossier_id is referenced) confirms the caller's tenant owns it.
import { NextRequest, NextResponse } from "next/server";
import { requireTenant, tenantHeaders, dossierIdFromReq, ownsDossier,
         notFound } from "@/lib/serverAuth";

export const dynamic = "force-dynamic";

const BFF = process.env.LIFECYCLE_BFF_URL || "http://127.0.0.1:8017";

async function forward(req: NextRequest, path: string[]) {
  const gate = await requireTenant(req);
  if (gate instanceof NextResponse) return gate;
  const did = dossierIdFromReq(req, path);
  if (did && !(await ownsDossier(gate, did))) return notFound(did);

  const suffix = path.map(encodeURIComponent).join("/");
  const qs = req.nextUrl.search || "";
  const url = `${BFF}/api/lifecycle/${suffix}${qs}`;
  const headers: Record<string, string> = { ...tenantHeaders(gate) };
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;

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
      { type: "about:blank", title: "lifecycle service unreachable",
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
