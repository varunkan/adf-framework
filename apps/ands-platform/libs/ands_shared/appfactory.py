"""FastAPI app factory — identical cross-cutting wiring for every service.

``create_app`` returns a FastAPI app with a health probe, a request-id
middleware (correlation across the mesh), and the shared problem+json handlers.
Services call it, then mount their own router.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from .ids import new_id
from .metrics import Metrics
from .problem import install_problem_handlers

REQUEST_ID_HEADER = "X-Request-ID"


def create_app(*, title: str, version: str = "0.1.0",
               description: str = "") -> FastAPI:
    app = FastAPI(title=title, version=version, description=description)
    app.state.metrics = Metrics(service=title)
    install_problem_handlers(app)

    @app.middleware("http")
    async def _observe(request: Request, call_next):  # noqa: ANN202
        rid = request.headers.get(REQUEST_ID_HEADER) or new_id()
        request.state.request_id = rid
        metrics = app.state.metrics
        metrics.inc_in_flight(1)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", None) or request.url.path
            metrics.observe_request(request.method, path, status,
                                    time.perf_counter() - start)
            metrics.inc_in_flight(-1)

    @app.get("/health", tags=["meta"])
    async def health():  # noqa: ANN202
        return {"status": "ok", "service": title, "version": version}

    @app.get("/metrics", tags=["meta"], response_class=PlainTextResponse)
    async def metrics_endpoint():  # noqa: ANN202
        return app.state.metrics.render()

    return app
