"""Gateway proxy behaviour, verified against an in-process stub upstream."""

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.main import build_app


def _stub_upstream() -> FastAPI:
    up = FastAPI()

    @up.get("/health")
    def health():
        return {"status": "ok"}

    @up.post("/api/collab/echo")
    async def echo(request: Request):
        return {"method": request.method, "seen": await request.json(),
                "rid": request.headers.get("X-Request-ID")}

    @up.get("/api/collab/items")
    def items(q: str = ""):
        return {"q": q}

    @up.get("/api/collab/boom")
    def boom():
        return JSONResponse(status_code=409, content={"title": "conflict"})

    return up


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=_stub_upstream())
    upstream = httpx.AsyncClient(transport=transport,
                                 base_url="http://collaboration")
    return TestClient(build_app(clients={"collaboration": upstream}))


def test_gateway_health_aggregates_upstreams(client):
    r = client.get("/gateway/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "services": {"collaboration": "ok"}}


def test_proxy_forwards_post_body_and_request_id(client):
    r = client.post("/api/collab/echo", json={"hi": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "POST"
    assert body["seen"] == {"hi": 1}
    assert body["rid"]  # gateway injected a correlation id


def test_proxy_forwards_query_string(client):
    r = client.get("/api/collab/items", params={"q": "hello"})
    assert r.status_code == 200
    assert r.json() == {"q": "hello"}


def test_proxy_passes_through_upstream_status(client):
    r = client.get("/api/collab/boom")
    assert r.status_code == 409
    assert r.json()["title"] == "conflict"
