"""REQ-092 — administrative / corrective sequences (relaxed content gate)."""

from app import admin_sequence


def test_withdrawal_sequence_needs_only_cover_letter():
    out = admin_sequence.build_admin_sequence({
        "dossier_id": "e123456", "activity": "withdrawal", "sequence": "0003",
        "operations": [{"op": "withdraw", "leaf_id": "m1-3-1-product-monograph"}]})
    assert out["valid"]
    seq = out["sequence"]
    assert seq["scientific_content_required"] is False
    assert seq["content_gate"]["can_pass"] is True
    assert seq["operations"][0]["op"] == "withdraw"


def test_relocate_carries_target_heading():
    out = admin_sequence.build_admin_sequence({
        "dossier_id": "e1", "activity": "reorganization", "sequence": "0004",
        "operations": [{"op": "relocate", "leaf_id": "l1",
                        "to_heading": "1.2"}]})
    assert out["sequence"]["operations"][0]["to_heading"] == "1.2"


def test_unknown_activity_and_op_rejected():
    bad = admin_sequence.build_admin_sequence({
        "dossier_id": "e1", "activity": "party", "sequence": "0003",
        "operations": [{"op": "yeet", "leaf_id": "l1"}]})
    rules = {e["rule"] for e in bad["errors"]}
    assert "admin_activity_invalid" in rules and "operation_unknown" in rules


def test_non_new_op_requires_target():
    bad = admin_sequence.build_admin_sequence({
        "dossier_id": "e1", "activity": "withdrawal", "sequence": "0003",
        "operations": [{"op": "delete"}]})
    assert any(e["rule"] == "operation_target_required" for e in bad["errors"])


def test_cover_letter_still_required_if_none():
    out = admin_sequence.build_admin_sequence({
        "dossier_id": "e1", "activity": "administrative-change",
        "sequence": "0003", "cover_letter_generated": False,
        "present_documents": []})
    assert out["valid"] is False
    assert out["sequence"]["content_gate"]["can_pass"] is False


def test_admin_sequence_api(client):
    r = client.post("/api/dossier/admin-sequence",
                    json={"dossier_id": "e1", "activity": "withdrawal",
                          "sequence": "0003",
                          "operations": [{"op": "withdraw", "leaf_id": "l1"}]})
    assert r.status_code == 201
    assert r.json()["sequence"]["activity"] == "withdrawal"
    bad = client.post("/api/dossier/admin-sequence",
                      json={"dossier_id": "e1", "activity": "party",
                            "sequence": "0003"})
    assert bad.status_code == 422
