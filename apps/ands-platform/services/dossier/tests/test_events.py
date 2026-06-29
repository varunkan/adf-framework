"""Event emissions — content-plan assignment & bilingual-PM blocker."""

from ands_shared import EventType


def test_assigning_item_publishes_event(ctx):
    plan = ctx.service.create_content_plan({"dossier_id": "e1",
                                            "submission_type": "ANDS"})
    ctx.service.assign_item(plan["items"][0]["id"], "bob", "2026-08-01")
    emitted = ctx.bus.events_of(EventType.CONTENT_PLAN_ITEM_ASSIGNED)
    assert len(emitted) == 1
    assert emitted[0].data["assignee"] == "bob"
    assert emitted[0].dossier_id == "e1"


def test_monograph_block_publishes_event(ctx):
    ctx.service.register_pm_leaf({"dossier_id": "e9", "lang": "en",
                                  "title": "EN PM"})
    ctx.service.monograph_status("e9")  # FR missing -> blocked
    emitted = ctx.bus.events_of(EventType.BILINGUAL_PM_BLOCKED)
    assert len(emitted) == 1
    assert emitted[0].dossier_id == "e9"


def test_complete_monograph_emits_no_block(ctx):
    ctx.service.register_pm_leaf({"dossier_id": "e9", "lang": "en",
                                  "title": "EN"})
    ctx.service.register_pm_leaf({"dossier_id": "e9", "lang": "fr",
                                  "title": "FR"})
    ctx.service.monograph_status("e9")
    assert ctx.bus.events_of(EventType.BILINGUAL_PM_BLOCKED) == []
