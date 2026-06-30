"""End-to-end event-mesh proof — real services, one shared bus.

These exercise the cross-service contracts that per-service tests can only assert
one side of: a single action in one service fans out, over the bus, into the
right reactions in three others.
"""


def _blocking_ctx(dossier="e1"):
    return {"dossier_id": dossier, "files": [
        {"path": "m1/ca/x.pdf", "kind": "pdf", "encrypted": True,
         "pdf_version": "1.6"}],
        "leaves": [{"leaf_id": "l", "href": "m1/ca/x.pdf", "checksum": "a"}]}


def _clean_ctx(dossier="e2"):
    return {"dossier_id": dossier, "files": [
        {"path": "m1/ca/x.pdf", "kind": "pdf", "pdf_version": "1.6"}],
        "leaves": [{"leaf_id": "l", "href": "m1/ca/x.pdf", "checksum": "a"}]}


def test_blocking_validation_fans_out_to_three_services(mesh):
    # ONE action: validation runs and finds a blocking defect, notify alice.
    mesh.validation.validate({"context": _blocking_ctx("e1"), "dossier_id": "e1",
                              "notify": ["alice"]})

    # collaboration turned validation.failed into a blocking-defect notification
    inbox = mesh.collaboration.inbox("alice")
    assert inbox["unread"] == 1
    assert inbox["notifications"][0]["kind"] == "blocking_defect"

    # readiness projected the dossier as BLOCKED
    assert mesh.readiness.get("e1")["status"] == "BLOCKED"

    # governance audited both validation events (wildcard subscription)
    actions = {e["action"] for e in
               mesh.governance.list_audit(dossier_id="e1")["events"]}
    assert {"validation.completed", "validation.failed"} <= actions


def test_clean_validation_is_ready_and_not_notified(mesh):
    mesh.validation.validate({"context": _clean_ctx("e2"), "dossier_id": "e2",
                              "notify": ["alice"]})
    assert mesh.readiness.get("e2")["status"] == "READY"
    assert mesh.collaboration.inbox("alice")["unread"] == 0   # no defect → no notice
    actions = {e["action"] for e in
               mesh.governance.list_audit(dossier_id="e2")["events"]}
    assert "validation.completed" in actions and "validation.failed" not in actions


def test_hc_ack_fans_out_to_collaboration_and_readiness(mesh):
    # drive a transmission to the HC acknowledgement, notify the filer
    mesh.transmission.submit({"dossier_id": "e3", "sequence": "0000",
                              "size_gb": 1})
    mesh.transmission.ack({"dossier_id": "e3", "kind": "fda",
                           "sequence": "0000", "core_id": "CORE-1"})
    mesh.transmission.ack({"dossier_id": "e3", "kind": "hc", "core_id": "CORE-1",
                           "notify": ["ra"]})

    # collaboration notified the filer of the HC receipt
    assert mesh.collaboration.inbox("ra")["unread"] == 1
    assert mesh.collaboration.inbox("ra")["notifications"][0]["kind"] == "hc_ack"

    # readiness shows the dossier as delivered
    tx_tile = next(t for t in mesh.readiness.get("e3")["tiles"]
                   if t["key"] == "transmission")
    assert tx_tile["delivered"] is True

    # governance audited the transmission events
    actions = {e["action"] for e in
               mesh.governance.list_audit(dossier_id="e3")["events"]}
    assert "transmission.hc_ack" in actions
