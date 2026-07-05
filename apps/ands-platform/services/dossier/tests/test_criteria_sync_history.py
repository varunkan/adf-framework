"""CAMP-CRITERIA-SYNC: criteria-sync transparency. A regulatory buyer's
adoption ask was "confirm the structural validator stays synced to HC criteria
versions as HC updates them." So the ruleset must expose an AUDITABLE, versioned
history (what changed at each version + when it was synced to HC) and a
"last reviewed / next review" maintenance cadence — proving the rules are
maintained, not stale. This ADDS to criteria()/rule_catalog()/parity(); it never
rewrites them.
"""

import datetime as _dt
import re

from app import ectd_validation


_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _is_iso_month_or_day(s: str) -> bool:
    return bool(_DATE_RE.match(s))


def test_criteria_history_lists_versions_including_current():
    hist = ectd_validation.criteria_history()
    entries = hist["history"]
    assert entries, "there must be at least one version history entry"
    versions = [e["version"] for e in entries]
    # the current profile version must appear in the history
    assert ectd_validation.CRITERIA_VERSION in versions
    # entries are ordered newest-first (the current version is at the top)
    assert versions[0] == ectd_validation.CRITERIA_VERSION


def test_every_history_entry_is_auditable():
    hist = ectd_validation.criteria_history()
    for e in hist["history"]:
        assert e.get("version"), "each entry needs a version"
        # an ISO-ish sync date so a buyer can audit *when* it was reconciled
        assert e.get("date") and _is_iso_month_or_day(e["date"]), e
        # what HC criteria version it was synced to
        assert e.get("synced_to"), f"{e['version']} must name the HC criteria it synced to"
        # a concrete changelog of what changed at that version
        assert e.get("changes") and isinstance(e["changes"], list) and e["changes"], e


def test_history_dates_are_monotonic_newest_first():
    hist = ectd_validation.criteria_history()
    dates = [e["date"] for e in hist["history"]]
    # newest-first: each date >= the next one (string compare works for ISO)
    assert dates == sorted(dates, reverse=True), dates


def test_review_cadence_is_stated_and_forward_looking():
    hist = ectd_validation.criteria_history()
    rev = hist["review"]
    assert rev.get("cadence"), "must state a review cadence (how often)"
    assert rev.get("last_reviewed") and _is_iso_month_or_day(rev["last_reviewed"])
    assert rev.get("next_review") and _is_iso_month_or_day(rev["next_review"])
    # next review must be AFTER last review — a real forward-looking commitment
    assert rev["next_review"] > rev["last_reviewed"], rev
    # the process note explains HOW the sync is maintained (honesty/auditability)
    assert rev.get("process")


def test_review_source_names_hc_criteria_authority():
    hist = ectd_validation.criteria_history()
    rev = hist["review"]
    blob = (rev.get("process", "") + " " + rev.get("cadence", "")).lower()
    # the cadence must reference reconciling against the HC published criteria
    assert "health canada" in blob or "hc" in blob


def test_criteria_embeds_review_block_so_it_travels():
    # the versioned criteria that stamps every validation surface must now also
    # carry the review cadence, so provenance-of-maintenance travels with a
    # validation report, not only via a separate endpoint.
    c = ectd_validation.criteria()
    assert c.get("review"), "criteria() must embed the review cadence block"
    assert c["review"].get("last_reviewed")
    assert c["review"].get("next_review")
    assert c["review"].get("cadence")


def test_criteria_history_carries_current_criteria():
    hist = ectd_validation.criteria_history()
    # the current versioned profile travels with the history so a report can
    # stamp "current: <name> v<version>, synced <date>".
    c = hist["criteria"]
    assert c["name"] and c["version"] == ectd_validation.CRITERIA_VERSION
    assert c.get("synced")


def test_current_version_history_matches_criteria_synced():
    # the top (current) history entry's synced_to must be consistent with the
    # criteria().synced string — one source of truth, not two drifting ones.
    hist = ectd_validation.criteria_history()
    top = hist["history"][0]
    synced = ectd_validation.criteria()["synced"]
    # the HC criteria version named in the current entry appears in criteria.synced
    assert top["synced_to"].split()[0] in synced or top["synced_to"] in synced, \
        (top["synced_to"], synced)


def test_web_endpoint_surfaces_criteria_history(client):
    r = client.get("/api/dossier/validation/criteria-history")
    assert r.status_code == 200
    body = r.json()
    assert body["history"] and body["review"]
    assert body["criteria"]["version"] == ectd_validation.CRITERIA_VERSION
    # every entry auditable over the wire too
    for e in body["history"]:
        assert e["version"] and e["date"] and e["synced_to"] and e["changes"]
    assert body["review"]["last_reviewed"] and body["review"]["next_review"]


def test_next_review_is_in_the_future_relative_to_last():
    # sanity: the cadence should produce a next_review that a buyer reads as a
    # live commitment. We don't hard-pin "today", but next_review must parse as
    # a valid date and be strictly after last_reviewed.
    rev = ectd_validation.criteria_history()["review"]
    def _parse(s: str) -> _dt.date:
        parts = [int(p) for p in s.split("-")]
        if len(parts) == 2:
            parts.append(1)
        return _dt.date(*parts)
    assert _parse(rev["next_review"]) > _parse(rev["last_reviewed"])
