"""Shared observability — every service exposes Prometheus /metrics (SAAS-NFR-006)."""


def test_metrics_endpoint_counts_requests(client):
    client.get("/health")
    client.post("/api/collab/tasks", json={"title": "t", "assignee": "bob"})
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "http_requests_total" in body
    assert 'service="collaboration"' in body
    assert "http_request_duration_seconds_count" in body
    assert "http_requests_in_flight" in body


def test_metrics_label_uses_route_template_not_raw_path(client):
    # two inboxes for different users collapse to one route series (low cardinality)
    client.get("/api/collab/inbox", params={"user": "a"})
    client.get("/api/collab/inbox", params={"user": "b"})
    body = client.get("/metrics").text
    assert 'route="/api/collab/inbox"' in body
