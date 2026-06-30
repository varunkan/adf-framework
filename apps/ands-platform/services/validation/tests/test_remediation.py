"""F9 / REQ-108 — PDF remediation pipeline."""

from ands_shared import EventType

from app import remediation


def _dirty_pdf():
    return {"path": "m1/ca/x.pdf", "kind": "pdf", "encrypted": True,
            "scanned": True, "searchable": False, "fonts_embedded": False,
            "bookmarks": False, "track_changes": True}


def test_plan_lists_applicable_ops():
    plan = remediation.remediation_plan(_dirty_pdf())
    assert {"decrypt", "ocr", "embed-fonts", "generate-bookmarks",
            "strip-track-changes"} <= set(plan)
    assert remediation.remediation_plan({"path": "clean.pdf"}) == []


def test_remediate_fixes_all_and_audits_changes():
    res = remediation.remediate_pdf(_dirty_pdf())
    after = res["after"]
    assert after["encrypted"] is False and after["searchable"] is True
    assert after["fonts_embedded"] is True and after["bookmarks"] is True
    assert after["track_changes"] is False
    assert res["remediated"] is True
    fields = {c["field"] for c in res["changes"]}
    assert "encrypted" in fields and "bookmarks" in fields
    # before is preserved unchanged (audit)
    assert res["before"]["encrypted"] is True


def test_remediate_selected_ops_only():
    res = remediation.remediate_pdf(_dirty_pdf(), ops=["decrypt"])
    assert res["after"]["encrypted"] is False
    assert res["after"]["bookmarks"] is False   # not requested
    assert {c["op"] for c in res["changes"]} == {"decrypt"}


def test_remediate_api_emits_event(ctx):
    r = ctx.client.post("/api/validation/remediate",
                        json={"file": _dirty_pdf(), "dossier_id": "e1"})
    assert r.json()["remediated"] is True
    assert len(ctx.bus.events_of(EventType.DOCUMENT_REMEDIATED)) == 1


def test_clean_pdf_no_event(ctx):
    ctx.client.post("/api/validation/remediate",
                    json={"file": {"path": "clean.pdf", "kind": "pdf"}})
    assert ctx.bus.events_of(EventType.DOCUMENT_REMEDIATED) == []
