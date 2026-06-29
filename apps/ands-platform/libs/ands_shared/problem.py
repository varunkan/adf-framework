"""RFC 9457 problem+json errors, shared across every service.

Services raise :class:`ProblemError`; :func:`install_problem_handlers` renders it
(and request-validation failures) as ``application/problem+json`` with a stable
shape, so clients and the gateway get one error contract everywhere.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

CONTENT_TYPE = "application/problem+json"


class ProblemError(Exception):
    """A domain/application error that maps to an HTTP problem response."""

    def __init__(self, status: int, title: str, *, detail: str = "",
                 type: str = "about:blank", **extra: Any) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type
        self.extra = extra

    def to_dict(self) -> dict:
        body = {"type": self.type, "title": self.title, "status": self.status}
        if self.detail:
            body["detail"] = self.detail
        body.update(self.extra)
        return body


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(_req: Request, exc: ProblemError):  # noqa: ANN202
        return JSONResponse(status_code=exc.status, content=exc.to_dict(),
                            media_type=CONTENT_TYPE)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError):  # noqa
        return JSONResponse(
            status_code=422,
            media_type=CONTENT_TYPE,
            content={"type": "about:blank", "title": "Unprocessable Entity",
                     "status": 422, "errors": exc.errors()},
        )
