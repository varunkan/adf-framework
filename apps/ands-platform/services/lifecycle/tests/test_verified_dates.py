"""Round-9 (operations BLOCKER, n=4) — per-clock verified-date overrides.

"I need it to reconcile against the real DIN/Right-to-Sell status and my
actual filed sequences, otherwise it's a parallel truth that drifts."

A verification records the user's externally-verified value for a calculated
clock: WHO verified it, WHEN, the SOURCE reference, and the calculated value
at the moment of verification (so a later drift is detectable). The store is
APPEND-ONLY — a re-verification adds a new record; history is never lost.
"""

from __future__ import annotations


def _post(client, body: dict, tenant: str = "", email: str = "qa@acme.test"):
    headers = {}
    if tenant:
        headers["X-Tenant-Id"] = tenant
    if email:
        headers["X-User-Email"] = email
    return client.post("/api/lifecycle/verified-date", json=body,
                       headers=headers)


BODY = {
    "dossier_id": "e1",
    "clock_key": "noa:n1:action_window",
    "verified_date": "2026-08-15",
    "calculated_date": "2026-08-15",
    "source_ref": "HC letter HC6-024-c2-2026 · Vault RIM record 4711",
}


def test_record_verified_date_captures_who_when_source(client):
    r = _post(client, BODY)
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["dossier_id"] == "e1"
    assert rec["clock_key"] == "noa:n1:action_window"
    assert rec["verified_date"] == "2026-08-15"
    assert rec["calculated_date"] == "2026-08-15"
    assert rec["source_ref"].startswith("HC letter")
    assert rec["verified_by"] == "qa@acme.test"
    assert rec["verified_at"]          # UTC stamp set server-side
    assert rec["discrepancy"] is False


def test_discrepancy_flagged_when_verified_differs_from_calculated(client):
    r = _post(client, {**BODY, "verified_date": "2026-08-20"})
    assert r.status_code == 201
    assert r.json()["discrepancy"] is True


def test_missing_fields_are_422(client):
    for missing in ("dossier_id", "clock_key", "verified_date", "source_ref"):
        r = _post(client, {**BODY, missing: ""})
        assert r.status_code == 422, missing


def test_bad_date_is_422(client):
    r = _post(client, {**BODY, "verified_date": "next tuesday"})
    assert r.status_code == 422


def test_list_returns_latest_per_clock_with_history(client):
    assert _post(client, BODY).status_code == 201
    # re-verification appends — it never overwrites the first record
    assert _post(client, {**BODY, "verified_date": "2026-08-22",
                          "source_ref": "corrected per HC phone call"},
                 email="ra@acme.test").status_code == 201
    assert _post(client, {**BODY, "clock_key": "rts:r9:2026-27",
                          "verified_date": "2026-10-01"}).status_code == 201

    r = client.get("/api/lifecycle/verified-dates?dossier_id=e1")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2                      # latest per clock_key
    by_key = {v["clock_key"]: v for v in body["verifications"]}
    latest = by_key["noa:n1:action_window"]
    assert latest["verified_date"] == "2026-08-22"  # newest wins for display
    assert latest["verified_by"] == "ra@acme.test"
    assert latest["history_count"] == 2             # append-only: both kept
    assert by_key["rts:r9:2026-27"]["history_count"] == 1


def test_tenant_isolation_on_list_and_write(client):
    assert _post(client, BODY, tenant="t-acme").status_code == 201
    # another tenant sees nothing for the same dossier id
    r = client.get("/api/lifecycle/verified-dates?dossier_id=e1",
                   headers={"X-Tenant-Id": "t-other"})
    assert r.status_code == 200
    assert r.json()["count"] == 0
    # the owner still sees it
    r = client.get("/api/lifecycle/verified-dates?dossier_id=e1",
                   headers={"X-Tenant-Id": "t-acme"})
    assert r.json()["count"] == 1
