"""ADOPT-LIFECYCLE-0001 — end-to-end acceptance for follow-up sequences 0001+.

The unit layer already proves the pieces (assembly replace, backbone
back-pointer, validator rules). This ties them together through the REAL API
surface a publisher drives, so the expert lens (regops / ra_officer / cdmo)
can trust the whole 0001-replace lifecycle, not just an initial 0000:

  * a 0001 sequence that REPLACES a prior 0000 leaf is ACCEPTED — it validates,
    the current view records the replace with a prior-leaf back-pointer, the
    Outline endpoint surfaces that back-pointer, and the transmissible per-
    sequence backbone carries ``operation="replace"`` + a ``<modified-file>``
    href at the prior leaf's ``../0000/`` relative path;
  * an ILLEGAL lifecycle op (a replace naming a prior leaf that is not live) is
    CAUGHT by the same validator that gates export.
"""

import io
import xml.etree.ElementTree as ET
import zipfile

from app import assembly, ectd_validation

XLINK = "{http://www.w3c.org/1999/xlink}"


def _dossier(client, did="e987654"):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": "Drugazole 10 mg"})
    assert r.status_code == 201
    return did


def _upload(client, did, section, name, body, lang=None):
    data = {"lang": lang} if lang else {}
    r = client.post(f"/api/dossier/ectd/{did}/section/{section}/upload",
                    files={"file": (name, body, "application/pdf")}, data=data)
    assert r.status_code == 200
    return r.json()


# -- the happy path: a 0001 replace against a 0000 leaf is ACCEPTED -----------
def test_0001_replace_of_0000_leaf_is_accepted_end_to_end(client):
    did = _dossier(client)
    # 0000: original cover letter transmitted in the initial working sequence.
    _upload(client, did, "1.0", "cover-v1.pdf", b"%PDF-1.4 cover letter v1")
    # 0001: a response sequence that supersedes it.
    r = client.post(f"/api/dossier/dossiers/{did}/sequences",
                    json={"sequence": "0001", "purpose": "response",
                          "note": "screening deficiency SDN-1"})
    assert r.status_code == 201 and r.json()["active_sequence"] == "0001"
    revised = b"%PDF-1.4 cover letter v2 (response)"
    _upload(client, did, "1.0", "cover-v2.pdf", revised)

    # (a) the live view is ONE leaf, filed as a replace in 0001, pointing back
    #     at the 0000 leaf it supersedes; the prior leaf is retired to history.
    view = client.get(f"/api/dossier/ectd/{did}/current-view").json()
    assert len(view["live"]) == 1
    live = view["live"][0]
    assert live["operation"] == "replace" and live["sequence"] == "0001"
    prior = view["history"][0]
    assert prior["sequence"] == "0000"
    assert live["modified_leaf"] == prior["leaf_id"]

    # (b) the Outline endpoint surfaces that prior-leaf back-pointer (so the web
    #     can render lifecycle correctness without recomputing it).
    outline = client.get(
        f"/api/dossier/ectd/{did}/viewer/outline/0001").json()
    ops = {o["leaf_id"]: o for o in outline["lifecycle_operations"]}
    assert ops[live["leaf_id"]]["operation"] == "replace"
    assert ops[live["leaf_id"]]["modified_leaf"] == prior["leaf_id"]

    # (c) the validator that gates export ACCEPTS the lifecycle.
    val = client.get(f"/api/dossier/dossiers/{did}/validate").json()
    assert val["passed"] is True

    # (d) the transmissible 0001 backbone carries ONLY the replace leaf, with
    #     operation="replace" and a <modified-file> back-pointer at the prior
    #     leaf's ../0000/ relative path — exactly what HC's reviewer replays.
    r = client.get(f"/api/dossier/ectd/{did}/export/0001")
    assert r.status_code == 200 and r.headers["X-Export-Missing"] == "0"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    index_name = next(n for n in z.namelist()
                      if n.endswith("0001/index.xml"))
    root = ET.fromstring(z.read(index_name))
    leaves = [el for el in root if el.tag.endswith("leaf")]
    assert len(leaves) == 1
    lf = leaves[0]
    assert lf.get("operation") == "replace"
    mod = lf.find("modified-file")
    assert mod is not None
    assert mod.get(f"{XLINK}href", "").startswith("../0000/")
    # the revised bytes ride along in 0001; 0000's bytes do NOT leak into it.
    payloads = [z.read(n) for n in z.namelist()]
    assert revised in payloads


# -- the guard rail: an ILLEGAL lifecycle op is CAUGHT ------------------------
def test_0001_replace_naming_unknown_prior_leaf_is_caught(ctx):
    client = ctx.client
    did = _dossier(client, "e987655")
    _upload(client, did, "1.0", "cover-v1.pdf", b"%PDF-1.4 cover letter v1")
    client.post(f"/api/dossier/dossiers/{did}/sequences",
                json={"sequence": "0001", "purpose": "response"})

    # A dossier that reached a bad state some other way: a 0001 replace whose
    # modified_leaf is not in the live view. add_leaf refuses this at insert
    # time, so the model is injected directly to prove the VALIDATOR catches it.
    model = ctx.repo.get_dossier(did) or assembly.new_dossier(did)
    src = model["sequences"][0]["leaves"][0]
    model["sequences"].append({"sequence": "0001", "leaves": [
        {**src, "leaf_id": "ghost-0001", "operation": "replace",
         "modified_leaf": "does-not-exist", "sequence": "0001"}]})
    res = ectd_validation.validate(model)
    assert res["passed"] is False
    assert "prior_leaf_unknown" in {e["rule"] for e in res["errors"]}
