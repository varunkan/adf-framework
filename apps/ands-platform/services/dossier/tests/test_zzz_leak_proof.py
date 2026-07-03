"""PROOF: WS3 durable ledger leaks a prior dossier's audit trail to a NEW,
unrelated dossier that reuses an ID freed by a rename. Happy path, no fault
injection. repository_sqlite.list_events -> _rename_chain_ids walks the chain
by ID string with no creation-epoch boundary."""


def _mk(client, did, title="x"):
    r = client.post("/api/dossier/dossiers", json={"dossier_id": did, "title": title})
    assert r.status_code in (200, 201), r.text


def test_reused_id_inherits_stranger_audit_trail(client):
    # 1. original a111111 gets a distinctive audit event
    _mk(client, "a111111")
    client.request("DELETE", "/api/dossier/dossiers/a111111",
                   json={"reason": "PATIENT-SAFETY-RECALL", "confirm_id": "a111111"})
    client.post("/api/dossier/dossiers/a111111/restore", json={"reason": "ok"})
    # 2. rename it away — a111111 is now a free ID, chain b222222->a111111 kept
    assert client.post("/api/dossier/dossiers/a111111/rename",
                       json={"new_id": "b222222"}).status_code == 200
    # 3. a brand-new, unrelated dossier reuses the freed ID a111111
    _mk(client, "a111111", title="Unrelated New Product")
    # 4. its history must NOT contain the prior dossier's events
    hist = client.get("/api/dossier/dossiers/a111111/history").json()["events"]
    leaked = [e for e in hist if e.get("reason") == "PATIENT-SAFETY-RECALL"]
    assert not leaked, (
        "AUDIT LEAK: new a111111 inherited prior dossier's ledger events: "
        f"{[(e['event_type'], e['reason']) for e in hist]}")
