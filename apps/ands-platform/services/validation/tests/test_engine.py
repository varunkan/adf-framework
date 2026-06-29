"""Pure validation engine — run / inline / fix."""

from app import engine
from tests.conftest import clean_context


def test_clean_context_has_no_findings():
    result = engine.run_validation(clean_context())
    assert result["findings"] == []
    assert not result["blocking"]
    assert result["error_count"] == 0


def test_encrypted_pdf_is_blocking_a09():
    ctx = clean_context()
    ctx["files"][0]["encrypted"] = True
    result = engine.run_validation(ctx)
    assert result["blocking"]
    assert any(f["rule_id"] == "A09" for f in result["errors"])


def test_missing_bookmarks_is_warning_not_blocking():
    ctx = clean_context()
    ctx["files"][0]["bookmarks"] = False
    result = engine.run_validation(ctx)
    assert not result["blocking"]
    assert any(f["rule_id"] == "A11" for f in result["warnings"])


def test_bad_pdf_version_and_naming_are_errors():
    ctx = clean_context()
    ctx["files"][0]["pdf_version"] = "2.0"
    ctx["files"].append({"path": "m1/ca/Bad Name.pdf", "kind": "pdf",
                         "pdf_version": "1.5"})
    result = engine.run_validation(ctx)
    rule_ids = {f["rule_id"] for f in result["errors"]}
    assert "D03" in rule_ids and "B32" in rule_ids


def test_inline_gutter_keys_by_file():
    ctx = clean_context()
    ctx["files"][0]["encrypted"] = True
    gutter = engine.inline_findings(ctx)["gutter"]
    assert "m1/ca/cover.pdf" in gutter
    assert gutter["m1/ca/cover.pdf"][0]["fix_id"] == "decrypt-pdf"


def test_apply_fix_clears_defect():
    ctx = clean_context()
    ctx["files"][0]["encrypted"] = True
    fixed = engine.apply_fix(ctx, "decrypt-pdf", "m1/ca/cover.pdf")
    assert engine.run_validation(fixed)["blocking"] is False


def test_unknown_fix_raises():
    import pytest
    with pytest.raises(ValueError):
        engine.apply_fix(clean_context(), "make-pretty", "x")
