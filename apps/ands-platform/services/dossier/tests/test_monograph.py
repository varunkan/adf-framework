"""Pure bilingual Product Monograph domain (REQ-098)."""

from app import monograph


def test_normalize_pm_leaf_valid_defaults_leaf_and_heading():
    out = monograph.normalize_pm_leaf({
        "dossier_id": "e123456", "lang": "EN", "title": "Metformin PM"})
    assert out["valid"]
    leaf = out["leaf"]
    assert leaf["lang"] == "en"
    assert leaf["heading"] == "1.3.1"
    assert leaf["leaf_id"] == "m1-3-1-product-monograph"
    assert leaf["version"] == 1


def test_normalize_pm_leaf_rejects_bad_lang_and_missing_fields():
    out = monograph.normalize_pm_leaf({"dossier_id": "", "lang": "de",
                                       "title": ""})
    rules = {e["rule"] for e in out["errors"]}
    assert not out["valid"]
    assert {"pm_lang_invalid", "pm_dossier_required",
            "pm_title_required"} <= rules


def test_language_pair_latest_version_wins():
    leaves = [
        {"lang": "en", "version": 1, "title": "EN v1"},
        {"lang": "en", "version": 3, "title": "EN v3"},
        {"lang": "fr", "version": 2, "title": "FR v2"},
    ]
    pair = monograph.pm_language_pair(leaves)
    assert pair["en"]["title"] == "EN v3"
    assert pair["fr"]["title"] == "FR v2"


def test_missing_fr_is_blocking():
    result = monograph.validate_bilingual_monograph(
        [{"lang": "en", "version": 1, "title": "EN"}])
    assert result["status"] == monograph.STATUS_BLOCKED
    assert result["blocking"]
    assert any(f["rule"] == "pm_fr_missing" for f in result["findings"])


def test_both_present_is_complete():
    result = monograph.validate_bilingual_monograph([
        {"lang": "en", "version": 2, "title": "EN"},
        {"lang": "fr", "version": 2, "title": "FR"}])
    assert result["status"] == monograph.STATUS_COMPLETE
    assert not result["blocking"]
    assert result["findings"] == []


def test_en_newer_than_fr_warns_not_blocks():
    result = monograph.validate_bilingual_monograph([
        {"lang": "en", "version": 3, "title": "EN"},
        {"lang": "fr", "version": 2, "title": "FR"}])
    assert not result["blocking"]
    assert any(f["rule"] == "pm_fr_out_of_sync"
               and f["severity"] == "warning" for f in result["findings"])
