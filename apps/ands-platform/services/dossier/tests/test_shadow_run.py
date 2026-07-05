"""CAMP-SHADOW — shadow / parallel-run affordance (de-risk the trial).

The one thing 16/24 task-eval personas said before trusting the tool live:
"I would run it in parallel against a filing we KNOW passed eValidator and diff
the tool's output against our validated publisher's output." This makes that a
first-class, in-app affordance.

A shadow run points the tool at a prior / known-good sequence, runs the SAME
structural validator + the import-compatibility self-check over the real package
bytes, and emits a STRUCTURED shadow-run comparison record: structural findings,
a leaf inventory (leaf_id / href / md5 / operation), lifecycle operations, and
package inventory — so the filer can diff the tool's view against their
validated publisher's output. When the filer supplies a known-good REFERENCE
(the leaves their publisher's validator saw — leaf_id/href/checksum), the tool
computes a leaf-level DIFF: matched / checksum-mismatch / only-in-tool /
only-in-reference.

Honest scope: this is a CONFIDENCE-BUILDING comparison (structural, over the
tool's own output), NOT a guarantee your sequence will pass HC's eValidator.

These tests are written FIRST (RED) and drive the pure module + service wiring.
They extend the TIER2-PARITY-UX / CAMP-INTEROP loop-closers; they never rewrite
them.
"""

import pytest

from ands_shared import ProblemError

from app import assembly, export_pkg, shadow_run


# ---------------------------------------------------------------------------
# pure-module builders
# ---------------------------------------------------------------------------

def _model_0000(did="e123456"):
    d = assembly.new_dossier(did)
    assembly.add_leaf(d, "0000", {"leaf_id": "pm", "operation": "new",
                                  "heading": "1.3.1", "title": "Drugazole PM"})
    assembly.add_leaf(d, "0000", {"leaf_id": "cl", "operation": "new",
                                  "heading": "1.0", "title": "Cover"})
    return d


def _pkg(model, seq="0000"):
    return export_pkg.build_package(
        model, seq, lambda lid: b"%PDF-1.7 body", b"<rt/>")


# ===========================================================================
# 1) pure module: a structured shadow-run comparison over a good sequence
# ===========================================================================

def test_shadow_report_over_good_sequence_is_diff_friendly():
    model = _model_0000()
    validation = {"passed": True, "errors": [], "warnings": [],
                  "criteria": {"disclaimer": "structural only"}}
    rep = shadow_run.build_shadow_report(
        model, "0000", _pkg(model), validation)
    # it names itself honestly as a comparison, not a guarantee
    assert rep["mode"] == "shadow"
    assert rep["dossier_id"] == "e123456"
    assert rep["sequence"] == "0000"
    assert "disclaimer" in rep and "guarantee" not in rep["disclaimer"].lower() \
        or "not" in rep["disclaimer"].lower()
    # the tool's structural verdict travels
    assert rep["validation"]["passed"] is True
    # the import-compatibility self-check ran over the real bytes
    assert rep["import_compat"]["compatible"] is True
    # a diff-friendly LEAF INVENTORY: leaf_id / href / md5 / operation
    inv = rep["leaf_inventory"]
    ids = {lf["leaf_id"] for lf in inv}
    assert ids == {"pm", "cl"}
    for lf in inv:
        assert lf["href"] and lf["md5"] and lf["operation"] == "new"
    # lifecycle operations are enumerated for the diff
    ops = {o["leaf_id"]: o["operation"] for o in rep["lifecycle_operations"]}
    assert ops == {"pm": "new", "cl": "new"}


def test_shadow_report_carries_package_inventory():
    model = _model_0000()
    validation = {"passed": True, "errors": [], "warnings": [], "criteria": {}}
    rep = shadow_run.build_shadow_report(model, "0000", _pkg(model), validation)
    # the package inventory is exactly what a parallel importer would find
    files = rep["import_compat"]["inventory"]["files"]
    assert any(f.endswith("index.xml") for f in files)
    assert any(f.endswith("ca-regional.xml") for f in files)


# ===========================================================================
# 2) pure module: the leaf-level DIFF against a known-good reference
# ===========================================================================

def _reference_from_inventory(inv, mutate=None):
    """Build a publisher-style reference (leaf_id/href/checksum) from an
    inventory, optionally mutating it to simulate a real diff."""
    ref = [{"leaf_id": lf["leaf_id"], "href": lf["href"],
            "checksum": lf["md5"]} for lf in inv]
    return mutate(ref) if mutate else ref


def test_shadow_diff_all_matched_when_reference_equals_tool_view():
    model = _model_0000()
    validation = {"passed": True, "errors": [], "warnings": [], "criteria": {}}
    rep = shadow_run.build_shadow_report(model, "0000", _pkg(model), validation)
    ref = _reference_from_inventory(rep["leaf_inventory"])
    diff = shadow_run.diff_against_reference(rep["leaf_inventory"], ref)
    assert diff["identical"] is True
    assert {m["leaf_id"] for m in diff["matched"]} == {"pm", "cl"}
    assert diff["checksum_mismatch"] == []
    assert diff["only_in_tool"] == []
    assert diff["only_in_reference"] == []


def test_shadow_diff_flags_checksum_mismatch():
    model = _model_0000()
    validation = {"passed": True, "errors": [], "warnings": [], "criteria": {}}
    rep = shadow_run.build_shadow_report(model, "0000", _pkg(model), validation)

    def bump(ref):
        ref[0]["checksum"] = "f" * 32   # publisher saw different bytes for pm
        return ref
    ref = _reference_from_inventory(rep["leaf_inventory"], bump)
    diff = shadow_run.diff_against_reference(rep["leaf_inventory"], ref)
    assert diff["identical"] is False
    mism = {m["leaf_id"] for m in diff["checksum_mismatch"]}
    assert mism == {"pm"}
    # a mismatch row shows both sides so the filer can reconcile
    row = diff["checksum_mismatch"][0]
    assert row["tool_md5"] != row["reference_checksum"]


def test_shadow_diff_flags_only_in_tool_and_only_in_reference():
    model = _model_0000()
    validation = {"passed": True, "errors": [], "warnings": [], "criteria": {}}
    rep = shadow_run.build_shadow_report(model, "0000", _pkg(model), validation)

    def drop_and_add(ref):
        ref = [r for r in ref if r["leaf_id"] != "cl"]   # publisher lacks cl
        ref.append({"leaf_id": "extra", "href": "m1/ca/99/extra.pdf",
                    "checksum": "a" * 32})               # publisher has extra
        return ref
    ref = _reference_from_inventory(rep["leaf_inventory"], drop_and_add)
    diff = shadow_run.diff_against_reference(rep["leaf_inventory"], ref)
    assert diff["identical"] is False
    assert {x["leaf_id"] for x in diff["only_in_tool"]} == {"cl"}
    assert {x["leaf_id"] for x in diff["only_in_reference"]} == {"extra"}


def test_shadow_report_embeds_diff_when_reference_supplied():
    model = _model_0000()
    validation = {"passed": True, "errors": [], "warnings": [], "criteria": {}}
    rep0 = shadow_run.build_shadow_report(model, "0000", _pkg(model), validation)
    ref = _reference_from_inventory(rep0["leaf_inventory"])
    rep = shadow_run.build_shadow_report(model, "0000", _pkg(model), validation,
                                         reference=ref)
    assert rep["diff"]["identical"] is True
    assert rep["has_reference"] is True


def test_shadow_report_without_reference_has_no_diff():
    model = _model_0000()
    validation = {"passed": True, "errors": [], "warnings": [], "criteria": {}}
    rep = shadow_run.build_shadow_report(model, "0000", _pkg(model), validation)
    assert rep["has_reference"] is False
    assert rep["diff"] is None


def test_diff_reference_is_tolerant_of_missing_fields():
    inv = [{"leaf_id": "pm", "href": "m1/pm.pdf", "md5": "b" * 32,
            "operation": "new"}]
    # a reference row with only a leaf_id (no checksum) must not crash — it is
    # matched by id, with the checksum comparison recorded as unknown.
    diff = shadow_run.diff_against_reference(inv, [{"leaf_id": "pm"}])
    assert {m["leaf_id"] for m in diff["matched"]} == {"pm"}
    assert diff["checksum_mismatch"] == []


# ===========================================================================
# 3) service: shadow_run over a real dossier + audit + honesty
# ===========================================================================

def _create(client, did="e123456", title="Attestol 10 mg tablet", tenant=None):
    headers = {"X-Tenant-Id": tenant} if tenant else {}
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _place_leaf(service, did, sequence, leaf_id, section="1.0"):
    """Place a real, content-bearing live leaf via the module builder (the real
    filer path) so its bytes are in the store and the package is complete."""
    service.upload_document(did, section, f"{leaf_id}.pdf", "application/pdf",
                            b"%PDF-1.4 cover letter bytes")


def test_service_shadow_run_produces_structured_comparison(ctx):
    _create(ctx.client, did="e222222")
    _place_leaf(ctx.service, "e222222", "0000", "cover-a")
    rep = ctx.service.shadow_run("e222222", "0000")
    assert rep["mode"] == "shadow"
    assert rep["dossier_id"] == "e222222"
    assert rep["sequence"] == "0000"
    assert rep["validation"]["passed"] is True
    assert rep["import_compat"]["compatible"] is True
    # the real filer path places the section's canonical leaf id
    assert {lf["leaf_id"] for lf in rep["leaf_inventory"]} == \
        {"m1-0-1-cover-letter"}
    # honesty travels — a comparison, not a guarantee, and not an eValidator claim
    assert rep["disclaimer"]
    assert rep["validation"]["criteria"]["disclaimer"]


def test_service_shadow_run_with_reference_diffs(ctx):
    _create(ctx.client, did="e333333")
    _place_leaf(ctx.service, "e333333", "0000", "cover-good")
    base = ctx.service.shadow_run("e333333", "0000")
    ref = [{"leaf_id": lf["leaf_id"], "href": lf["href"],
            "checksum": lf["md5"]} for lf in base["leaf_inventory"]]
    rep = ctx.service.shadow_run("e333333", "0000", reference=ref)
    assert rep["has_reference"] is True
    assert rep["diff"]["identical"] is True


def test_service_shadow_run_records_audit_event(ctx):
    _create(ctx.client, did="e444444")
    _place_leaf(ctx.service, "e444444", "0000", "cover-x")
    ctx.service.shadow_run("e444444", "0000")
    h = ctx.client.get("/api/dossier/dossiers/e444444/history")
    types = {e["event_type"] for e in h.json()["events"]}
    assert any("shadow" in t for t in types), types


def test_service_shadow_run_unknown_sequence_404(ctx):
    _create(ctx.client, did="e555555")
    _place_leaf(ctx.service, "e555555", "0000", "cover-y")
    with pytest.raises(ProblemError):
        ctx.service.shadow_run("e555555", "9999")


def test_service_shadow_run_unknown_dossier_404(ctx):
    with pytest.raises(ProblemError):
        ctx.service.shadow_run("e000000", "0000")


# ===========================================================================
# 4) API + tenant isolation
# ===========================================================================

def _upload(client, did, section="1.0", name="cover.pdf"):
    files = {"file": (name, b"%PDF-1.4 cover letter bytes", "application/pdf")}
    r = client.post(f"/api/dossier/ectd/{did}/section/{section}/upload",
                    files=files)
    assert r.status_code in (200, 201), r.text


def test_shadow_run_endpoint(client):
    _create(client, did="e666666")
    _upload(client, "e666666")
    r = client.post("/api/dossier/dossiers/e666666/shadow-run/0000")
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["mode"] == "shadow"
    assert body["sequence"] == "0000"
    assert body["import_compat"]["compatible"] is True


def test_shadow_run_endpoint_with_reference_body(client):
    _create(client, did="e777777")
    _upload(client, "e777777")
    base = client.post("/api/dossier/dossiers/e777777/shadow-run/0000").json()
    ref = [{"leaf_id": lf["leaf_id"], "href": lf["href"],
            "checksum": lf["md5"]} for lf in base["leaf_inventory"]]
    r = client.post("/api/dossier/dossiers/e777777/shadow-run/0000",
                    json={"reference": ref})
    assert r.status_code in (200, 201), r.text
    assert r.json()["diff"]["identical"] is True


def test_shadow_run_endpoint_tenant_isolated(client):
    _create(client, did="e888888", tenant="acme")
    r = client.post("/api/dossier/dossiers/e888888/shadow-run/0000",
                    headers={"X-Tenant-Id": "rival"})
    assert r.status_code == 404, r.text
