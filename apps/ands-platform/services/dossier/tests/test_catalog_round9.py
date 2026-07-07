"""Round-9 usability backlog — Dossier Catalog (`catalog`) service items.

Covers:
- catalog/"Dossier ID validation is format-only" (n=5): create-side format
  enforcement, live/archived collision rejection, and the workspace-convention
  (admin-configurable) extra format rule.
- catalog/"'Soonest due' dates have no defined source or regulatory clock"
  (n=8): the named-clock meta (source + driving plan item) on the list payload.
- catalog/"REP Dossier ID Request flow unexplained and untracked" (n=7): the
  per-dossier REP request summary on the catalog list payload.
- catalog/"List view lacks sequence/lifecycle and validation status" (n=4):
  the lifecycle block + live structural-check summary on the list payload.
- catalog/"No bilingual/French support surfaced anywhere on the page" (n=2):
  the bilingual-PM language-status block on the list payload.
- catalog/"Due/overdue flags absent from the audit view" (n=1): soonest-due
  meta on the archived (recoverable trash) list too.
"""


def _mk(client, did="e123456", **kw):
    body = {"dossier_id": did, "title": kw.pop("title", "Drugazole 10 mg")}
    body.update(kw)
    return client.post("/api/dossier/dossiers", json=body)


def _plan_with_due(client, did, due="2099-01-15"):
    """Create a content plan and put a due date on its first item; returns
    the item that now drives the dossier's soonest-due named clock."""
    plan = client.post("/api/dossier/content-plans",
                       json={"dossier_id": did, "submission_type": "ANDS",
                             "cs_be_only": True}).json()["plan"]
    item = plan["items"][0]
    r = client.post("/api/dossier/content-plans/item/assign",
                    json={"id": item["id"], "assignee": "pm@cro.example",
                          "due_date": due})
    assert r.status_code == 200
    return item


# ── Dossier ID validation: format + uniqueness + convention rule ────────────

def test_create_rejects_bad_format(client):
    for bad in ("bogus!!", "e12", "123456", "ee123456"):
        r = _mk(client, bad)
        assert r.status_code == 422, bad
        assert r.json()["rule"] == "dossier_id_format"


def test_create_accepts_real_and_placeholder_ids(client):
    assert _mk(client, "e123456").status_code == 201
    assert _mk(client, "d431509").status_code == 201   # draft placeholder


def test_create_normalizes_case_like_rename_does(client):
    # ' E123456 ' → 'e123456' (same normalization as the set-real-ID path)
    r = _mk(client, " E123456 ")
    assert r.status_code == 201
    assert r.json()["dossier_id"] == "e123456"


def test_create_rejects_live_collision(client):
    assert _mk(client, "e123456").status_code == 201
    r = _mk(client, "e123456", title="Second dossier, same HC file")
    assert r.status_code == 409
    assert r.json()["rule"] == "dossier_id_taken"


def test_create_rejects_archived_collision_with_restore_hint(client):
    assert _mk(client, "e123456").status_code == 201
    r = client.request("DELETE", "/api/dossier/dossiers/e123456",
                       json={"reason": "duplicate created in error",
                             "confirm_id": "e123456"})
    assert r.status_code == 200
    r = _mk(client, "e123456")
    assert r.status_code == 409
    assert r.json()["rule"] == "dossier_id_archived"
    assert "restore" in (r.json().get("detail") or "").lower()


def test_create_workspace_convention_rule(client, monkeypatch):
    # admin-configurable client convention: only e + 6 digits in this workspace
    monkeypatch.setenv("ANDS_DOSSIER_ID_CONVENTION_RE", r"^e\d{6}$")
    monkeypatch.setenv("ANDS_DOSSIER_ID_CONVENTION_NOTE",
                       "Acme CRO convention: e + 6 digits")
    r = _mk(client, "e1234567")           # valid base format, breaks convention
    assert r.status_code == 422
    assert r.json()["rule"] == "dossier_id_convention"
    assert "Acme CRO convention" in (r.json().get("detail") or "")
    assert _mk(client, "e123456").status_code == 201


def test_placeholder_ids_bypass_convention_rule(client, monkeypatch):
    # a draft placeholder is not a client-mandated REAL id — never blocked
    monkeypatch.setenv("ANDS_DOSSIER_ID_CONVENTION_RE", r"^e\d{6}$")
    assert _mk(client, "d431509").status_code == 201


# ── Named-clock soonest-due meta on the catalog list ─────────────────────────

def test_list_names_the_due_date_clock(client):
    _mk(client, "e123456")
    item = _plan_with_due(client, "e123456", due="2099-01-15")
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["soonest_due"] == "2099-01-15"
    meta = row["soonest_due_meta"]
    assert meta["date"] == "2099-01-15"
    assert meta["clock_type"] == "client-set target"
    assert meta["item_id"] == item["id"]
    assert meta["item_title"] == item["title"]
    assert meta["assignee"] == "pm@cro.example"


def test_list_soonest_due_meta_null_without_plan_dates(client):
    _mk(client, "e123456")
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["soonest_due"] is None
    assert row["soonest_due_meta"] is None


# ── REP request summary on the catalog list ──────────────────────────────────

def test_list_carries_rep_request_summary(client):
    _mk(client, "d431509")
    r = client.post("/api/dossier/dossiers/d431509/rep-request", json={})
    assert r.status_code == 201
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    rep = row["rep_request"]
    assert rep["transmitted"] is False           # honesty flag survives
    assert rep["requested_at"]
    # summary only — the full guidance payload stays on the rep-request GET
    assert "guidance" not in rep


def test_list_rep_request_null_when_never_requested(client):
    _mk(client, "d431509")
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["rep_request"] is None


# ── Lifecycle block + live structural summary on the catalog list ────────────

def test_list_carries_lifecycle_block(client):
    _mk(client, "e123456")
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["lifecycle"] == {"active_sequence": "0000",
                                "sequence_count": 1, "purpose": "initial"}
    client.post("/api/dossier/dossiers/e123456/sequences",
                json={"sequence": "0001", "purpose": "response",
                      "note": "screening response"})
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["lifecycle"] == {"active_sequence": "0001",
                                "sequence_count": 2, "purpose": "response"}


def test_list_carries_structural_summary_and_evalidator_state(client):
    _mk(client, "e123456")
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    s = row["structural"]
    assert isinstance(s["passed"], bool)
    assert isinstance(s["error_count"], int)
    assert isinstance(s["warning_count"], int)
    # the user-attested eValidator state travels too — honestly not cleared
    assert row["evalidator"]["cleared"] is False
    assert row["evalidator"]["source"] == "user_attested_external"


# ── Bilingual PM language-status block on the catalog list ───────────────────

def test_list_bilingual_pm_status(client):
    _mk(client, "e123456")
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["bilingual_pm"] == {"status": "none", "en": False, "fr": False}
    client.post("/api/dossier/monograph/leaves",
                json={"dossier_id": "e123456", "lang": "en", "title": "EN PM"})
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["bilingual_pm"] == {"status": "blocked", "en": True, "fr": False}
    client.post("/api/dossier/monograph/leaves",
                json={"dossier_id": "e123456", "lang": "fr", "title": "FR PM"})
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["bilingual_pm"] == {"status": "complete", "en": True, "fr": True}


# ── Due flags reach the archived (recoverable trash) view too ────────────────

def test_archived_list_carries_soonest_due_meta(client):
    _mk(client, "e123456")
    _plan_with_due(client, "e123456", due="2099-01-15")
    r = client.request("DELETE", "/api/dossier/dossiers/e123456",
                       json={"reason": "duplicate created in error",
                             "confirm_id": "e123456"})
    assert r.status_code == 200
    rows = client.get("/api/dossier/dossiers/archived").json()["dossiers"]
    assert rows[0]["soonest_due"] == "2099-01-15"
    assert rows[0]["soonest_due_meta"]["clock_type"] == "client-set target"
