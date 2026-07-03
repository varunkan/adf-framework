"""WS3 record-integrity — day-counter PROVENANCE data contract.

The portfolio NoaChip and the NOA-register clocks show a day-COUNT (e.g. "36d
for brand to act"). WS3 attaches a provenance popover to each such number so a
reviewer can trace it to its anchor date, source and counting rule — WITHOUT
fabricating any legal date. That popover reads specific fields off the lifecycle
``GET /noa`` payload. This test pins that contract: if the service ever stops
returning an anchor field, the popover would be forced to invent one — so the
build must fail here first.
"""


def _create(client, **over):
    body = {"dossier_id": "e1", "patent_number": "CA2500000",
            "allegation": "not_infringed", "form_v_date": "2025-02-01"}
    body.update(over)
    return client.post("/api/lifecycle/noa", json=body)


def test_served_allegation_exposes_45day_provenance_anchors(client):
    nid = _create(client).json()["id"]
    client.post(f"/api/lifecycle/noa/{nid}/serve",
                json={"served_date": "2025-03-01"})
    row = client.get("/api/lifecycle/noa",
                     params={"dossier_id": "e1", "as_of": "2025-03-10"}) \
        .json()["allegations"][0]
    # the popover's 45-day anchor = the served date (operator-keyed), the window
    # end, the days-remaining and the as_of it was computed against — all real,
    # none invented.
    assert row["status"] == "served"
    assert row["served_date"] == "2025-03-01"          # provenance anchor
    assert row["action_window_end"] == "2025-04-15"    # rule result
    assert row["action_days_remaining"] == 36          # displayed count
    assert row["as_of"] == "2025-03-10"                # counted-as-of


def test_stay_running_allegation_exposes_24month_provenance_anchors(client):
    nid = _create(client).json()["id"]
    client.post(f"/api/lifecycle/noa/{nid}/serve",
                json={"served_date": "2025-03-01"})
    client.post(f"/api/lifecycle/noa/{nid}/action",
                json={"action_date": "2025-04-01", "court_file": "T-1000-25"})
    row = client.get("/api/lifecycle/noa",
                     params={"dossier_id": "e1", "as_of": "2026-04-01"}) \
        .json()["allegations"][0]
    # the popover's 24-month anchor = the s.6 action-commencement date; the
    # stay end and remaining days are the counted result.
    assert row["status"] == "stay_running"
    assert row["action_date"] == "2025-04-01"          # provenance anchor
    assert row["stay_start"] == "2025-04-01"
    assert row["stay_end"] == "2027-04-01"             # rule result
    assert row["stay_days_remaining"] == 365           # displayed count
    assert row["as_of"] == "2026-04-01"
