"""F3 / G-P2-07 — token-bucket rate limiting (shared kernel)."""

from fastapi.testclient import TestClient

from ands_shared import create_app
from ands_shared.ratelimit import RateLimiter


def test_token_bucket_refills_over_time():
    rl = RateLimiter(rate=1.0, burst=2)
    assert rl.allow("k", now=100.0)
    assert rl.allow("k", now=100.0)
    assert not rl.allow("k", now=100.0)     # burst exhausted
    assert rl.allow("k", now=101.0)         # +1s → 1 token back
    assert rl.allow("other", now=100.0)     # per-key isolation


def test_middleware_returns_429_problem_after_burst():
    app = create_app(title="t", rate_limit=0.0001, burst=2)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    blocked = client.get("/ping")
    assert blocked.status_code == 429
    assert blocked.headers["content-type"].startswith("application/problem+json")
    assert blocked.headers["Retry-After"] == "1"


def test_health_and_metrics_are_exempt():
    app = create_app(title="t", rate_limit=0.0001, burst=1)
    client = TestClient(app)
    for _ in range(5):
        assert client.get("/health").status_code == 200
        assert client.get("/metrics").status_code == 200


def test_disabled_by_default():
    app = create_app(title="t")  # no rate_limit → unlimited

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    assert all(client.get("/ping").status_code == 200 for _ in range(10))
