"""Pure readiness projection (REQ-071)."""

from app import readiness


def test_no_signals_blocks_on_validation_not_run():
    r = readiness.readiness("e1", {})
    assert r["status"] == "BLOCKED"
    assert any(b["rule"] == "validation_not_run" for b in r["blocking_items"])


def test_clean_validation_is_ready():
    r = readiness.readiness("e1", {"validation": {"ran": True, "errors": 0,
                                                  "warnings": 0}})
    assert r["status"] == "READY" and r["ready"] is True


def test_validation_errors_block():
    r = readiness.readiness("e1", {"validation": {"ran": True, "errors": 3}})
    assert r["status"] == "BLOCKED"
    assert any(b["rule"] == "validation_errors" and b["count"] == 3
               for b in r["blocking_items"])


def test_bilingual_pm_block():
    r = readiness.readiness("e1", {"validation": {"ran": True, "errors": 0},
                                   "bilingual_pm": {"blocked": True}})
    assert r["status"] == "BLOCKED"
    assert any(b["rule"] == "bilingual_pm_blocked" for b in r["blocking_items"])


def test_transmission_delivered_is_a_pass_tile():
    r = readiness.readiness("e1", {"validation": {"ran": True, "errors": 0},
                                   "transmission": {"state": "RECEIVED_BY_HC"}})
    tx = next(t for t in r["tiles"] if t["key"] == "transmission")
    assert tx["delivered"] is True and tx["state"] == "pass"
    assert r["status"] == "READY"   # delivery is not a blocker


def test_dashboard_rollup():
    projections = {
        "e1": {"validation": {"ran": True, "errors": 0}},     # ready
        "e2": {"validation": {"ran": True, "errors": 1}},     # blocked
        "e3": {},                                             # blocked
    }
    dash = readiness.dashboard(projections)
    assert dash["total"] == 3 and dash["ready"] == 1 and dash["blocked"] == 2
