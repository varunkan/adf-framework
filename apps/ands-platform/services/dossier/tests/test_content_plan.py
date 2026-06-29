"""Pure content-plan domain (REQ-103)."""

import pytest

from app import content_plan


def test_ands_template_items_and_leaf_mapping():
    items = content_plan.build_plan_items("ANDS")
    keys = [i["key"] for i in items]
    assert keys == ["cover-letter", "application-form", "product-monograph",
                    "qos-ce", "cmc-body", "be-study-report"]
    pm = next(i for i in items if i["key"] == "product-monograph")
    assert pm["section"] == "1.3.1"
    assert pm["leaf_id"] == "m1-3-1-product-monograph"  # resolved from placement
    assert all(i["status"] == content_plan.ITEM_PENDING for i in items)


def test_cs_be_only_adds_cs_be_copy_after_pm():
    items = content_plan.build_plan_items("ANDS", cs_be_only=True)
    keys = [i["key"] for i in items]
    assert "cs-be-copy" in keys
    assert keys.index("cs-be-copy") == keys.index("product-monograph") + 1


def test_lowercase_and_sands_supported():
    assert [i["key"] for i in content_plan.build_plan_items("sands")][0] \
        == "cover-letter"
    assert content_plan.is_valid_submission_type("ANDS")
    assert not content_plan.is_valid_submission_type("XYZ")


def test_unknown_submission_type_raises():
    with pytest.raises(ValueError):
        content_plan.build_plan_items("XYZ")


def test_plan_progress_counts_required_only():
    items = content_plan.build_plan_items("ANDS")  # 6 required
    prog = content_plan.plan_progress(items)
    assert prog["total"] == 6 and prog["done"] == 0 and prog["pct"] == 0
    items[0]["status"] = content_plan.ITEM_COMPLETE  # 1.0 cover letter
    items[2]["status"] = content_plan.ITEM_COMPLETE  # 1.3.1 PM
    prog = content_plan.plan_progress(items)
    assert prog["done"] == 2 and prog["pct"] == 33 and not prog["complete"]
    assert prog["by_module"]["1"]["done"] >= 1


def test_progress_complete_when_all_required_done():
    items = content_plan.build_plan_items("ANDS")
    for i in items:
        i["status"] = content_plan.ITEM_COMPLETE
    prog = content_plan.plan_progress(items)
    assert prog["complete"] and prog["pct"] == 100


def test_validate_item_status_and_due_date():
    assert content_plan.validate_item_status("complete")
    assert not content_plan.validate_item_status("banana")
    assert content_plan.validate_due_date("2026-08-01")
    assert content_plan.validate_due_date("")
    assert not content_plan.validate_due_date("next tuesday")
