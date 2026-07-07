"""Round-9 validate_export backlog — backend acceptance tests (TDD, RED first).

Covers:
- Item 1  (BLOCKER, staleness): ectd_validation.staleness() — a loud
  review-overdue warning whenever today's month passes CRITERIA_REVIEW's
  next_review, embedded in criteria() with an honest limitation statement
  (ANDS Studio cannot detect an HC republication automatically).
- Item 10 (coverage exhaustive): criteria()['coverage'] names bookmarks/
  hyperlinks, page dimensions, folder depth explicitly, and criteria()
  carries a checksum_note documenting the leaf md5 is computed exactly as
  eCTD 3.2.2 expects — labeled document control, not validation.
- Item 12 (bilingual flag): a PROMINENT (first) not_checked entry flags
  bilingual (EN/FR) content / French mock-ups as NOT checked here.
- Item 14 (how-to-fix): every rule in rule_catalog() carries a non-empty
  one-line how_to_fix hint (incl. CA-REP-0001).
"""
from datetime import date

from app import ectd_validation as ev


# ---------------------------------------------------------------- item 1

def test_staleness_not_overdue_before_next_review():
    nr = ev.CRITERIA_REVIEW["next_review"]  # "YYYY-MM"
    year, month = int(nr[:4]), int(nr[5:7])
    before = date(year, month, 1)  # the review month itself is not yet overdue
    s = ev.staleness(today=before)
    assert s["review_overdue"] is False
    assert s["next_review"] == nr
    assert "OVERDUE" not in s["message"]


def test_staleness_overdue_after_next_review():
    nr = ev.CRITERIA_REVIEW["next_review"]
    year, month = int(nr[:4]), int(nr[5:7])
    # first month AFTER the scheduled review month → overdue
    after = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    s = ev.staleness(today=after)
    assert s["review_overdue"] is True
    # LOUD: the message must announce the overdue state and warn the ruleset
    # may trail HC's current published criteria.
    assert "OVERDUE" in s["message"]
    assert "trail" in s["message"].lower()
    # actionable: point at where HC publishes the current criteria
    assert "canada.ca" in s["verify_at"]


def test_staleness_limitation_is_honest():
    s = ev.staleness(today=date(2030, 1, 1))
    # The honest limit: the tool cannot detect HC republication automatically.
    assert "cannot" in s["limitation"].lower()
    assert "automatic" in s["limitation"].lower()
    assert "canada.ca" in s["limitation"] or "canada.ca" in s["verify_at"]


def test_criteria_carries_staleness_block():
    c = ev.criteria()
    s = c["staleness"]
    assert set(s) >= {"review_overdue", "as_of", "synced_to", "next_review",
                      "message", "verify_at", "limitation"}
    assert isinstance(s["review_overdue"], bool)
    assert s["synced_to"] == ev.CRITERIA_SYNCED


# ---------------------------------------------------------------- item 10

def test_not_checked_names_the_asked_specifics():
    nc = "\n".join(ev.criteria()["coverage"]["not_checked"]).lower()
    assert "bookmark" in nc
    assert "hyperlink" in nc
    assert "page dimension" in nc or "page size" in nc
    assert "folder depth" in nc
    assert "path" in nc  # path-length limits


def test_checksum_note_documents_md5_exactly():
    c = ev.criteria()
    note = c["checksum_note"]
    # names the algorithm, the input, and the spec convention
    assert "MD5" in note or "md5" in note
    assert "byte" in note.lower()
    assert "3.2.2" in note
    assert "32" in note and "hex" in note.lower()
    # the protected copy rule: document control, not validation — and the
    # checksum wording never sits near the word "validated".
    assert "document control, not validation" in note
    assert "validated" not in note.lower()


# ---------------------------------------------------------------- item 12

def test_bilingual_not_checked_entry_is_prominent_and_honest():
    nc = ev.criteria()["coverage"]["not_checked"]
    first = nc[0].lower()
    # PROMINENT: listed first, names bilingual/French + mock-ups
    assert "bilingual" in first or "en/fr" in first
    assert "french" in first
    assert "mock-up" in first or "mockup" in first
    # honest: names where EN/FR PM pairing IS enforced (the M1 monograph gate)
    joined = "\n".join(nc).lower()
    assert "module 1" in joined or "monograph" in joined


# ---------------------------------------------------------------- item 14

def test_every_rule_carries_a_how_to_fix_hint():
    cat = ev.rule_catalog()
    assert cat["count"] == len(cat["rules"])
    for r in cat["rules"]:
        assert r.get("how_to_fix", "").strip(), (
            f"rule {r['rule_id']} ({r['rule']}) has no how_to_fix hint")
    # the REP guardrail row is included and hints at the REP request path
    rep = next(r for r in cat["rules"] if r["rule_id"] == "CA-REP-0001")
    assert "rep" in rep["how_to_fix"].lower()
