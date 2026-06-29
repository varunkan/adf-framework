"""FastAPI app factory — identical cross-cutting wiring for every service.

``create_app`` returns a FastAPI app with a health probe, a request-id
middleware (correlation across the mesh), and the shared problem+json handlers.
Services call it, then mount their own router.
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from .ids import new_id
from .problem import install_problem_handlers

REQUEST_ID_HEADER = "X-Request-ID"


def create_app(*, title: str, version: str = "0.1.0",
               description: str = "") -> FastAPI:
    app = FastAPI(title=title, version=version, description=description)
    install_problem_handlers(app)

    @app.middleware("http")
    async def _request_id(request: Request, call_next):  # noqa: ANN202
        rid = request.headers.get(REQUEST_ID_HEADER) or new_id()
        request.state.request_id = rid
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid
        return response

    @app.get("/health", tags=["meta"])
    async def health():  # noqa: ANN202
        return {"status": "ok", "service": title, "version": version}

    return app
