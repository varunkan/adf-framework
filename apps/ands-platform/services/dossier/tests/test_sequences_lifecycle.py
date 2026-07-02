"""Working sequences 0001+ — purposes, the ACTIVE pointer and the
cross-sequence replace lifecycle a regulatory response must carry."""

import io
import zipfile


def _dossier(client, did="e123456"):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": "Drugazole 10 mg"})
    assert r.status_code == 201
    return did


def _seqs(client, did):
    r = client.get(f"/api/dossier/dossiers/{did}/sequences")
    assert r.status_code == 200
    return r.json()


def _upload(client, did, section, name, body, lang=None):
    data = {"lang": lang} if lang else {}
    r = client.post(f"/api/dossier/ectd/{did}/section/{section}/upload",
                    files={"file": (name, body, "application/pdf")}, data=data)
    assert r.status_code == 200
    return r.json()


# -- sequence catalog ---------------------------------------------------------
def test_new_dossier_has_active_initial_sequence(client):
    did = _dossier(client)
    body = _seqs(client, did)
    assert body["active_sequence"] == "0000"
    assert body["sequences"] == [
        {"sequence": "0000", "purpose": "initial", "note": "",
         "leaf_count": 0, "active": True}]


def test_create_response_sequence_becomes_active(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/dossiers/{did}/sequences",
                    json={"sequence": "0001", "purpose": "response",
                          "note": "screening deficiency SDN-1"})
    assert r.status_code == 201
    body = r.json()
    assert body["active_sequence"] == "0001"
    by_seq = {s["sequence"]: s for s in body["sequences"]}
    assert by_seq["0001"]["purpose"] == "response"
    assert by_seq["0001"]["note"] == "screening deficiency SDN-1"
    assert by_seq["0001"]["active"] is True
    assert by_seq["0000"]["active"] is False


def test_sequence_purpose_validated(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/dossiers/{did}/sequences",
                    json={"sequence": "0001", "purpose": "nonsense"})
    assert r.status_code == 422


def test_activate_switches_back_and_unknown_404(client):
    did = _dossier(client)
    client.post(f"/api/dossier/dossiers/{did}/sequences",
                json={"sequence": "0001", "purpose": "response"})
    r = client.post(f"/api/dossier/dossiers/{did}/sequences/0000/activate")
    assert r.status_code == 200
    body = r.json()
    assert body["active_sequence"] == "0000"
    # activation never rewrites the sequence's recorded purpose
    by_seq = {s["sequence"]: s for s in body["sequences"]}
    assert by_seq["0001"]["purpose"] == "response"
    r = client.post(f"/api/dossier/dossiers/{did}/sequences/0009/activate")
    assert r.status_code == 404


# -- cross-sequence replace lifecycle -----------------------------------------
def test_replace_lifecycle_across_sequences(client):
    did = _dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate", json={})
    client.post(f"/api/dossier/dossiers/{did}/sequences",
                json={"sequence": "0001", "purpose": "response"})
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate", json={})
    view = client.get(f"/api/dossier/ectd/{did}/current-view").json()
    assert len(view["live"]) == 1
    leaf = view["live"][0]
    assert leaf["operation"] == "replace" and leaf["sequence"] == "0001"
    prior = view["history"][0]
    assert prior["sequence"] == "0000"
    assert leaf["modified_leaf"] == prior["leaf_id"]
    counts = {s["sequence"]: s["leaf_count"]
              for s in _seqs(client, did)["sequences"]}
    assert counts == {"0000": 1, "0001": 1}


def test_replace_is_idempotent_within_working_sequence(client):
    did = _dossier(client)
    _upload(client, did, "1.0", "cover-v1.pdf", b"%PDF-1.4 v1")
    client.post(f"/api/dossier/dossiers/{did}/sequences",
                json={"sequence": "0001", "purpose": "response"})
    _upload(client, did, "1.0", "cover-v2.pdf", b"%PDF-1.4 v2")
    content = _upload(client, did, "1.0", "cover-v3.pdf", b"%PDF-1.4 v3")
    view = client.get(f"/api/dossier/ectd/{did}/current-view").json()
    assert len(view["live"]) == 1
    assert view["live"][0]["operation"] == "replace"
    counts = {s["sequence"]: s["leaf_count"]
              for s in _seqs(client, did)["sequences"]}
    assert counts == {"0000": 1, "0001": 1}
    # the lifecycle replay stays structurally valid
    assert content["validation"]["passed"] is True


def test_first_filing_in_response_sequence_is_new(client):
    did = _dossier(client)
    client.post(f"/api/dossier/dossiers/{did}/sequences",
                json={"sequence": "0001", "purpose": "response"})
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate", json={})
    live = client.get(f"/api/dossier/ectd/{did}/current-view").json()["live"]
    assert len(live) == 1
    assert live[0]["operation"] == "new" and live[0]["sequence"] == "0001"


# -- per-sequence export ------------------------------------------------------
def test_export_of_response_sequence_contains_only_its_files(client):
    did = _dossier(client)
    ds = b"%PDF-1.4 drug substance bytes"
    _upload(client, did, "3.2.S.1", "ds.pdf", ds)
    _upload(client, did, "1.0", "cover-v1.pdf", b"%PDF-1.4 cover v1")
    client.post(f"/api/dossier/dossiers/{did}/sequences",
                json={"sequence": "0001", "purpose": "response"})
    revised = b"%PDF-1.4 cover v2 (response)"
    _upload(client, did, "1.0", "cover-v2.pdf", revised)

    r = client.get(f"/api/dossier/ectd/{did}/export/0001")
    assert r.status_code == 200
    assert r.headers["X-Export-Missing"] == "0"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert all(n.startswith(f"{did}/0001/") for n in names)
    payloads = [z.read(n) for n in names]
    assert revised in payloads          # the 0001 replace leaf rides along
    assert ds not in payloads           # 0000's leaves stay out of 0001

    # the initial sequence still exports its own (unreplaced) documents
    r0 = client.get(f"/api/dossier/ectd/{did}/export/0000")
    assert r0.headers["X-Export-Missing"] == "0"
    z0 = zipfile.ZipFile(io.BytesIO(r0.content))
    assert ds in [z0.read(n) for n in z0.namelist()]


def test_bilingual_replace_exports_in_response_sequence(client):
    did = _dossier(client)
    for lang in ("en", "fr"):
        _upload(client, did, "1.3.1", f"pm-{lang}.pdf",
                b"%PDF-1.4 pm " + lang.encode(), lang=lang)
    client.post(f"/api/dossier/dossiers/{did}/sequences",
                json={"sequence": "0001", "purpose": "response"})
    revised = b"%PDF-1.4 pm en revised"
    _upload(client, did, "1.3.1", "pm-en-v2.pdf", revised, lang="en")

    r = client.get(f"/api/dossier/ectd/{did}/export/0001")
    assert r.status_code == 200
    assert r.headers["X-Export-Missing"] == "0"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert revised in [z.read(n) for n in z.namelist()]
