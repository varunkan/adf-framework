"""Pure ruleset catalog/versioning (ported HC rules)."""

import pytest

from app import rules


def test_version_filters_catalog():
    ids_53 = {r["rule_id"] for r in rules.get_ruleset("5.3")["rules"]}
    ids_52 = {r["rule_id"] for r in rules.get_ruleset("5.2")["rules"]}
    # A02 became effective in 5.3 only
    assert "A02" in ids_53 and "A02" not in ids_52
    assert ids_52 < ids_53


def test_ruleset_catalog_is_serialisable():
    cat = rules.ruleset_catalog("5.3")
    assert cat["version"] == "5.3"
    sample = cat["rules"][0]
    assert set(sample) == {"rule_id", "category", "severity", "description",
                           "ruleset_version"}
    assert "check" not in sample  # no callables leak to the wire


def test_unknown_version_raises():
    with pytest.raises(rules.UnknownRulesetError):
        rules.get_ruleset("9.9")
