"""Golden-path end-to-end — the whole 10-service mesh, one ANDS journey.

Drives a generic sponsor from signup through a filed, approved, marketed ANDS,
asserting that every service plays its part AND that the event mesh fans the
journey into the readiness dashboard and the governance audit trail. This is the
sandbox 'golden dossier' (SAAS-REQ-008) realised as a runnable proof.
"""

DOSSIER = "e123456"


def _clean_validation_ctx():
    return {"dossier_id": DOSSIER, "files": [
        {"path": "m1/ca/pm.pdf", "kind": "pdf", "pdf_version": "1.6"}],
        "leaves": [{"leaf_id": "pm", "href": "m1/ca/pm.pdf", "checksum": "a"}]}


def test_golden_path_signup_to_marketed(mesh):
    # 1. identity — a generic sponsor self-serves a trial tenant.
    signup = mesh.identity.signup({"email": "ra@acme.io",
                                   "password": "acmePass123",
                                   "company_name": "Acme Generics"})
    assert signup["token"] and signup["tenant"]["status"] == "trial"

    # 2. dossier — content plan, eCTD leaves, bilingual Product Monograph.
    plan = mesh.dossier.create_content_plan({"dossier_id": DOSSIER,
                                             "submission_type": "ANDS"})
    assert plan["progress"]["total"] == 6
    mesh.dossier.add_leaf({"dossier_id": DOSSIER, "sequence": "0000",
                           "leaf_id": "pm", "operation": "new",
                           "heading": "1.3.1", "title": "PM"})
    for lang in ("en", "fr"):
        mesh.dossier.register_pm_leaf({"dossier_id": DOSSIER, "lang": lang,
                                       "title": f"PM ({lang})"})
    assert mesh.dossier.monograph_status(DOSSIER)["status"] == "complete"

    # 3. fees — the ANDS comparative-studies fee for the fiscal year.
    assert mesh.fees.ands_fee("2025-06-01")["amount"] == 70750.0

    # 4. validation — a clean run; the event projects into readiness + audit.
    result = mesh.validation.validate({"context": _clean_validation_ctx(),
                                       "dossier_id": DOSSIER})
    assert result["blocking"] is False

    # 5. transmission — configure, pass the Test gateway, submit, full ack chain.
    mesh.transmission.configure({"dossier_id": DOSSIER,
                                 "account_type": "WebTrader",
                                 "x509_certificate": "PEM"})
    mesh.transmission.test_round_trip({"dossier_id": DOSSIER})
    mesh.transmission.submit({"dossier_id": DOSSIER, "sequence": "0000",
                              "size_gb": 1})
    mesh.transmission.ack({"dossier_id": DOSSIER, "kind": "fda",
                           "sequence": "0000", "core_id": "CORE-1"})
    mesh.transmission.ack({"dossier_id": DOSSIER, "kind": "hc",
                           "core_id": "CORE-1", "notify": ["ra@acme.io"]})

    # 6. lifecycle — received → screening accepted → NOC issued.
    mesh.lifecycle.start_lifecycle({"dossier_id": DOSSIER,
                                    "submission_type": "ANDS",
                                    "received_date": "2025-01-06"})
    sal = mesh.lifecycle.transition({"dossier_id": DOSSIER, "kind": "screening",
                                     "value": "SAL", "date": "2025-01-10"})
    approved = mesh.lifecycle.transition({"dossier_id": DOSSIER,
                                          "kind": "decision", "value": "NOC",
                                          "date": sal["review_due"]})
    assert approved["status"] == "Approved"

    # 7. registry — register the marketed product post-NOC.
    reg = mesh.registry.create({"product": "Metformin 500mg",
                                "dossier_id": DOSSIER, "din": "02431234",
                                "drug_type": "prescription"})
    mesh.registry.set_status(reg["id"], "NOC-Issued")
    marketed = mesh.registry.set_status(reg["id"], "Marketed")
    assert marketed["status"] == "Marketed"

    # --- the mesh reacted across services, no direct calls ---------------
    # collaboration notified the filer of the HC acknowledgement
    assert mesh.collaboration.inbox("ra@acme.io")["unread"] == 1

    # readiness projected the dossier READY (clean validation, delivered, no PM block)
    card = mesh.readiness.get(DOSSIER)
    assert card["status"] == "READY"
    tx = next(t for t in card["tiles"] if t["key"] == "transmission")
    assert tx["delivered"] is True

    # governance audited the whole journey from the event stream
    actions = {e["action"] for e in
               mesh.governance.list_audit(dossier_id=DOSSIER)["events"]}
    assert {"validation.completed", "transmission.hc_ack",
            "lifecycle.transitioned", "registration.status_changed"} <= actions
