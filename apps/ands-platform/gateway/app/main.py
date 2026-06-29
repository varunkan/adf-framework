"""API gateway / BFF — routes external traffic to the service mesh.

A thin reverse proxy: each ``/api/<ctx>/*`` prefix forwards to the owning
service over HTTP, preserving method, query, body and the correlation request-id.
Upstream clients are injectable so tests drive real services in-process via an
ASGI transport (no network). As contexts come online, add a prefix→service entry.
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request, Response

from ands_shared import create_app
from ands_shared.appfactory import REQUEST_ID_HEADER

# bounded-context prefix -> (service name, default URL env)
SERVICES = {
    "collaboration": os.environ.get("COLLAB_URL", "http://collaboration:8000"),
    "dossier": os.environ.get("DOSSIER_URL", "http://dossier:8000"),
    "validation": os.environ.get("VALIDATION_URL", "http://validation:8000"),
}
PREFIX_TO_SERVICE = {
    "/api/collab": "collaboration",
    "/api/dossier": "dossier",
    "/api/validation": "validation",
}

# hop-by-hop headers we never forward verbatim
_SKIP_REQUEST_HEADERS = {"host", "content-length"}


def build_app(clients: dict | None = None) -> FastAPI:
    app = create_app(title="gateway", description="ANDS API gateway / BFF")
    app.state.clients = clients or {
        name: httpx.AsyncClient(base_url=url) for name, url in SERVICES.items()}

    async def _proxy(service: str, request: Request) -> Response:
        client: httpx.AsyncClient = app.state.clients[service]
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in _SKIP_REQUEST_HEADERS}
        headers[REQUEST_ID_HEADER] = getattr(request.state, "request_id", "")
        upstream = await client.request(
            request.method, path, content=await request.body(), headers=headers)
        return Response(
            content=upstream.content, status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type"))

    @app.api_route("/api/collab/{rest:path}",
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def collab(rest: str, request: Request):  # noqa: ANN202, ARG001
        return await _proxy("collaboration", request)

    @app.api_route("/api/dossier/{rest:path}",
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def dossier(rest: str, request: Request):  # noqa: ANN202, ARG001
        return await _proxy("dossier", request)

    @app.api_route("/api/validation/{rest:path}",
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def validation(rest: str, request: Request):  # noqa: ANN202, ARG001
        return await _proxy("validation", request)

    @app.get("/gateway/health", tags=["meta"])
    async def gateway_health():  # noqa: ANN202
        """Aggregate health across all wired upstream services."""
        statuses = {}
        for name, client in app.state.clients.items():
            try:
                r = await client.get("/health")
                statuses[name] = "ok" if r.status_code == 200 else "degraded"
            except Exception:
                statuses[name] = "unreachable"
        healthy = all(v == "ok" for v in statuses.values())
        return {"status": "ok" if healthy else "degraded", "services": statuses}

    return app


app = build_app()
