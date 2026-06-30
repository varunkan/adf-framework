"""FastAPI app factory — identical cross-cutting wiring for every service.

``create_app`` returns a FastAPI app with a health probe, a request-id
middleware (correlation across the mesh), and the shared problem+json handlers.
Services call it, then mount their own router.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .ids import new_id
from .metrics import Metrics
from .problem import CONTENT_TYPE as PROBLEM_TYPE
from .problem import install_problem_handlers
from .ratelimit import RateLimiter

REQUEST_ID_HEADER = "X-Request-ID"
_EXEMPT_PATHS = ("/health", "/metrics")


def create_app(*, title: str, version: str = "0.1.0", description: str = "",
               rate_limit: float | None = None,
               burst: int | None = None) -> FastAPI:
    app = FastAPI(title=title, version=version, description=description)
    app.state.metrics = Metrics(service=title)
    install_problem_handlers(app)

    # Rate limiting is off unless a rate is given (arg or ANDS_RATE_LIMIT env).
    rate = (rate_limit if rate_limit is not None
            else float(os.environ.get("ANDS_RATE_LIMIT", "0") or 0))
    cap = burst if burst is not None else int(
        os.environ.get("ANDS_RATE_BURST", "120") or 120)
    if rate > 0:
        limiter = RateLimiter(rate, cap)

        @app.middleware("http")
        async def _ratelimit(request: Request, call_next):  # noqa: ANN202
            if request.url.path in _EXEMPT_PATHS:
                return await call_next(request)
            key = (request.headers.get("X-Tenant-ID")
                   or (request.client.host if request.client else "anon"))
            if not limiter.allow(key):
                return JSONResponse(
                    status_code=429, media_type=PROBLEM_TYPE,
                    headers={"Retry-After": "1"},
                    content={"type": "about:blank", "title": "Too Many Requests",
                             "status": 429, "detail": "rate limit exceeded"})
            return await call_next(request)

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
