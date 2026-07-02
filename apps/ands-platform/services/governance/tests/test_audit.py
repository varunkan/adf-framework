"""Event-sourced audit trail — governance records every bus event."""

from ands_shared import EventEnvelope, EventType


def test_every_published_event_is_recorded(ctx):
    ctx.bus.publish(EventEnvelope.make(EventType.VALIDATION_FAILED,
                                       source="validation", dossier_id="e1",
                                       data={"rule": "A09"}))
    ctx.bus.publish(EventEnvelope.make(EventType.TRANSMISSION_HC_ACK,
                                       source="transmission", dossier_id="e1",
                                       data={"core_id": "C1"}))
    audit = ctx.service.list_audit()
    assert audit["count"] == 2
    actions = [e["action"] for e in audit["events"]]
    assert "validation.failed" in actions and "transmission.hc_ack" in actions


def test_audit_filter_by_dossier(ctx):
    ctx.bus.publish(EventEnvelope.make("x.y", source="s", dossier_id="e1"))
    ctx.bus.publish(EventEnvelope.make("x.z", source="s", dossier_id="e2"))
    assert ctx.service.list_audit(dossier_id="e1")["count"] == 1


def test_audit_trail_is_append_only_ordered(ctx):
    for i in range(3):
        ctx.bus.publish(EventEnvelope.make(f"evt.{i}", source="s"))
    seqs = [e["seq"] for e in ctx.service.list_audit()["events"]]
    assert seqs == sorted(seqs)  # monotonic order preserved


# -- HTTP ingest (services on per-process buses post events directly) -------

def test_http_ingest_lands_on_the_same_trail(ctx):
    ctx.bus.publish(EventEnvelope.make("x.first", source="s", dossier_id="e1"))
    rec = ctx.service.record_external({
        "source": "dossier", "event_type": "document.uploaded",
        "dossier_id": "e1", "tenant_id": "t1", "data": {"leaf": "l1"}})
    assert rec["category"] == "dossier"
    assert rec["action"] == "document.uploaded"
    events = ctx.service.list_audit(dossier_id="e1")["events"]
    assert [e["action"] for e in events] == ["x.first", "document.uploaded"]
    assert events[1]["detail"] == {"leaf": "l1"}
    assert events[1]["tenant_id"] == "t1"
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)  # ingest respects bus-event ordering


def test_http_ingest_requires_source_type_and_dossier(ctx):
    import pytest
    from ands_shared import ProblemError

    with pytest.raises(ProblemError):
        ctx.service.record_external({"source": "dossier"})


def test_list_audit_newest_first_with_limit(ctx):
    for i in range(5):
        ctx.bus.publish(EventEnvelope.make(f"evt.{i}", source="s",
                                           dossier_id="e9"))
    out = ctx.service.list_audit(dossier_id="e9", limit=2, newest_first=True)
    assert out["count"] == 2
    assert [e["action"] for e in out["events"]] == ["evt.4", "evt.3"]


# -- cross-tenant isolation (CRO regulatory: no data leakage across tenants) --

def _seed_two_tenants(ctx):
    """One audited event per tenant, plus one unowned (no tenant) event."""
    ctx.bus.publish(EventEnvelope.make("a.evt", source="s", dossier_id="da",
                                       tenant_id="tenant-a"))
    ctx.bus.publish(EventEnvelope.make("b.evt", source="s", dossier_id="db",
                                       tenant_id="tenant-b"))
    ctx.bus.publish(EventEnvelope.make("u.evt", source="s", dossier_id="du"))


def test_audit_list_isolates_tenants(ctx):
    _seed_two_tenants(ctx)
    a = ctx.service.list_audit(tenant_id="tenant-a")
    assert a["count"] == 1 and a["events"][0]["action"] == "a.evt"
    # tenant B never sees tenant A's row (nor the unowned one)
    b = ctx.service.list_audit(tenant_id="tenant-b")
    assert b["count"] == 1 and b["events"][0]["action"] == "b.evt"
    # no tenant context (in-process mesh / tests) stays UNSCOPED
    assert ctx.service.list_audit()["count"] == 3


def test_audit_export_isolates_tenants(ctx):
    _seed_two_tenants(ctx)
    a = ctx.service.export_audit(tenant_id="tenant-a")
    assert "a.evt" in a and "b.evt" not in a and "u.evt" not in a
    # unscoped export still contains everything
    allx = ctx.service.export_audit()
    assert "a.evt" in allx and "b.evt" in allx and "u.evt" in allx


def test_audit_endpoint_scopes_by_tenant_header(ctx):
    _seed_two_tenants(ctx)
    r = ctx.client.get("/api/governance/audit",
                       headers={"X-Tenant-Id": "tenant-a"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1 and body["events"][0]["action"] == "a.evt"
    # tenant B's row is invisible to tenant A
    assert all(e["tenant_id"] == "tenant-a" for e in body["events"])
    # no header -> unscoped (existing tests / mesh)
    assert ctx.client.get("/api/governance/audit").json()["count"] == 3


def test_audit_export_endpoint_scopes_by_tenant_header(ctx):
    _seed_two_tenants(ctx)
    r = ctx.client.get("/api/governance/audit/export",
                       headers={"X-Tenant-Id": "tenant-b"})
    assert r.status_code == 200
    assert "b.evt" in r.text and "a.evt" not in r.text and "u.evt" not in r.text
