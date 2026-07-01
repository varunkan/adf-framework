"""Cross-service: the journey BFF drives the real dossier eCTD engine.

Proves start → submission (provisions the dossier) → the content gate reads the
REAL dossier completeness → generating/uploading the required documents flips the
gate → the journey 'content' step advances → the assembled Files/Outline views
reflect the placed leaves.
"""

import pytest

from ands_shared import ProblemError


def _fill_all_required(dossier, dossier_id):
    """Author (generate) or upload every required document section."""
    cs = dossier.content_state(dossier_id)
    for m in cs["modules"]:
        for n in m["nodes"]:
            if n["applicability"] != "required" or n["kind"] != "document":
                continue
            if "generate" in n["affordances"] and n["generator_key"]:
                dossier.generate_document(dossier_id, n["section"], {})
            elif n["bilingual"]:
                for lang in ("en", "fr"):
                    dossier.upload_document(dossier_id, n["section"],
                                            f"{n['id']}-{lang}.pdf",
                                            "application/pdf", b"bytes", lang=lang)
            else:
                dossier.upload_document(dossier_id, n["section"],
                                        f"{n['id']}.pdf", "application/pdf",
                                        b"bytes")


def test_journey_submission_provisions_dossier_and_content_gate_is_real(mesh):
    j, d = mesh.journey, mesh.dossier
    sid = j.start({})["id"]
    j.advance(sid, "orient", {})
    j.advance(sid, "company", {"company_id": "12345"})
    j.advance(sid, "dossier", {"dossier_id": "e123456"})
    j.advance(sid, "submission", {"applicant": "Acme", "drug_product": "Drugazole"})

    # the dossier now exists in the dossier service (provisioned by the journey)
    full = d.get_dossier_full("e123456")
    assert full["index"]["dossier_id"] == "e123456"

    # the journey's content view is sourced from the real dossier + blocks
    view = j.get(sid)
    assert view["content"]["source"] == "dossier"
    assert view["content"]["gate"]["complete"] is False
    with pytest.raises(ProblemError):
        j.advance(sid, "content", {})            # required docs still missing

    # author + upload every required document + arrange the fee, then the gate
    # passes (the gate enforces content + fee-arranged + a clean eCTD validation)
    _fill_all_required(d, "e123456")
    d.set_fee_status("e123456", fee_paid=True, sme_granted=False)
    assert d.content_state("e123456")["gate"]["complete"] is True
    out = j.advance(sid, "content", {})          # now advances
    assert out["signals"]["content_done"] is True

    # the assembled Files view reflects the placed leaves (e.g. the cover letter)
    files = d.files_view("e123456")
    leaves = [lf for nd in files["nodes"] for lf in nd["leaves"]]
    assert any(lf["leaf_id"] == "m1-0-1-cover-letter" for lf in leaves)
    assert files["live_leaf_count"] > 10
