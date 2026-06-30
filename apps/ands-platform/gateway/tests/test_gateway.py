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

    @up.get("/api/dossier/ping")
    def dossier_ping():
        return {"pong": True}

    @up.get("/api/validation/ping")
    def validation_ping():
        return {"pong": "validation"}

    @up.get("/api/identity/ping")
    def identity_ping():
        return {"pong": "identity"}

    @up.get("/api/lifecycle/ping")
    def lifecycle_ping():
        return {"pong": "lifecycle"}

    @up.get("/api/fees/ping")
    def fees_ping():
        return {"pong": "fees"}

    @up.get("/api/transmission/ping")
    def transmission_ping():
        return {"pong": "transmission"}

    @up.get("/api/governance/ping")
    def governance_ping():
        return {"pong": "governance"}

    @up.get("/api/readiness/ping")
    def readiness_ping():
        return {"pong": "readiness"}

    @up.get("/api/registry/ping")
    def registry_ping():
        return {"pong": "registry"}

    @up.get("/api/webhooks/ping")
    def webhooks_ping():
        return {"pong": "webhooks"}

    @up.get("/api/journey/ping")
    def journey_ping():
        return {"pong": "journey"}

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


def test_gateway_service_catalog(client):
    cat = client.get("/gateway/services").json()
    services = {r["service"] for r in cat["routes"]}
    assert "collaboration" in services and "registry" in services
    assert cat["count"] == len(services)


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


def test_other_prefixes_route_to_their_service():
    transport = httpx.ASGITransport(app=_stub_upstream())
    up = httpx.AsyncClient(transport=transport, base_url="http://x")
    client = TestClient(build_app(clients={
        "collaboration": up, "dossier": up, "validation": up, "identity": up,
        "lifecycle": up, "fees": up, "transmission": up, "governance": up,
        "readiness": up, "registry": up, "webhooks": up, "journey": up}))
    assert client.get("/api/dossier/ping").json() == {"pong": True}
    assert client.get("/api/validation/ping").json() == {"pong": "validation"}
    assert client.get("/api/identity/ping").json() == {"pong": "identity"}
    assert client.get("/api/lifecycle/ping").json() == {"pong": "lifecycle"}
    assert client.get("/api/fees/ping").json() == {"pong": "fees"}
    assert client.get("/api/transmission/ping").json() == {"pong": "transmission"}
    assert client.get("/api/governance/ping").json() == {"pong": "governance"}
    assert client.get("/api/readiness/ping").json() == {"pong": "readiness"}
    assert client.get("/api/registry/ping").json() == {"pong": "registry"}
    assert client.get("/api/webhooks/ping").json() == {"pong": "webhooks"}
    assert client.get("/api/journey/ping").json() == {"pong": "journey"}
