"""POLISH-SIGN-BANNER: a lightweight signature-readiness signal on the dossier
state payload so ANY page (esp. the workspace chrome / DossierHeader) can show a
PERSISTENT, ambient banner the MOMENT the current package stops being cleanly
signed — a leaf changed after signing, or a conflicted (author-signs) sign
occurred — WITHOUT the reviewer having to open the pre-flight report.

ra_director (twice): the multi-sign flow leaves conflicted/stale signatures on
the record that the pre-flight only reconciles at the end; make the
signature-not-hand-off-ready state loud and ambient, not a status field to go
read.

This reuses ``_signature_status`` (the SAME collapse the pre-flight computes) —
no new sign logic. It proves ``content_state`` carries a ``signature_readiness``
block with:
  - ``signed`` — is there a manifest at all,
  - ``status`` — one of unsigned / verified / stale_unverified / sod_conflict,
  - ``handoff_ready`` — only ``verified`` is hand-off-ready,
  - ``needs_resign`` — the loud banner trigger: signed AND not verified,
  - ``message`` — the same plain-language line the pre-flight surfaces.

Honesty: this is a role-separation + tamper-evidence signal, NOT a Health Canada
acceptance claim — the message text already carries that.
"""

from app import audit_hook


def _create(client, did="p700001", title="Bannerol 5 mg tablet", tenant=None):
    headers = {"X-Tenant-Id": tenant} if tenant else {}
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title},
                    headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _place_leaf(ctx, did, *, author, body=b"%PDF-1.4 cover"):
    audit_hook.set_actor(author)
    try:
        ctx.service.upload_document(did, "1.0", "cover.pdf",
                                    "application/pdf", body)
    finally:
        audit_hook.set_actor("")
    return ctx.service._current_leaf_checksums(did)


def _manifest(leaves, *, signer, manifest_id="mani-banner"):
    return {
        "signer": signer, "role": "authorized_signer", "auth_method": "mfa",
        "meaning": "approved", "reason": "I attest.",
        "at": "2026-07-04T00:00:00+00:00", "tz": "UTC",
        "manifest_id": manifest_id, "leaf_count": len(leaves),
        "artifacts": [{"id": lid, "kind": "leaf", "checksum": cs,
                       "checksum_type": "MD5"} for lid, cs in leaves.items()],
    }


def test_signature_readiness_present_and_unsigned(ctx):
    _create(ctx.client, did="p700001")
    state = ctx.service.content_state("p700001")
    assert "signature_readiness" in state
    sr = state["signature_readiness"]
    assert sr["signed"] is False
    assert sr["status"] == "unsigned"
    assert sr["handoff_ready"] is False
    # unsigned is a NORMAL pre-sign state — it must NOT trigger the loud
    # "not cleanly signed, re-sign required" banner.
    assert sr["needs_resign"] is False
    assert sr["message"]


def test_signature_readiness_verified_no_banner(ctx):
    _create(ctx.client, did="p700002")
    leaves = _place_leaf(ctx, "p700002", author="author@sponsor.example")
    ctx.service.record_esign(
        "p700002", _manifest(leaves, signer="qa@sponsor.example"),
        actor="qa@sponsor.example")
    sr = ctx.service.content_state("p700002")["signature_readiness"]
    assert sr["signed"] is True
    assert sr["status"] == "verified"
    assert sr["handoff_ready"] is True
    # cleanly signed -> the banner clears
    assert sr["needs_resign"] is False


def test_signature_readiness_stale_triggers_banner(ctx):
    _create(ctx.client, did="p700003")
    leaves = _place_leaf(ctx, "p700003", author="author@sponsor.example")
    ctx.service.record_esign(
        "p700003", _manifest(leaves, signer="qa@sponsor.example"),
        actor="qa@sponsor.example")
    # a leaf changes AFTER signing (a 0001 replace / re-upload) — the stored
    # signature is now legitimately stale. The banner MUST fire ambiently.
    _place_leaf(ctx, "p700003", author="author@sponsor.example",
                body=b"%PDF-1.4 cover REVISED")
    sr = ctx.service.content_state("p700003")["signature_readiness"]
    assert sr["signed"] is True
    assert sr["status"] == "stale_unverified"
    assert sr["handoff_ready"] is False
    assert sr["needs_resign"] is True
    # the message names WHY + what to do (a distinct approver re-signs)
    assert "re-sign" in sr["message"].lower()


def test_signature_readiness_sod_conflict_triggers_banner(ctx):
    _create(ctx.client, did="p700004")
    # the SAME identity authors AND signs — a segregation-of-duties conflict.
    leaves = _place_leaf(ctx, "p700004", author="amir@sponsor.example")
    ctx.service.record_esign(
        "p700004", _manifest(leaves, signer="amir@sponsor.example"),
        actor="amir@sponsor.example")
    sr = ctx.service.content_state("p700004")["signature_readiness"]
    assert sr["signed"] is True
    assert sr["status"] == "sod_conflict"
    assert sr["handoff_ready"] is False
    assert sr["needs_resign"] is True
    assert "author" in sr["message"].lower()


def test_signature_readiness_matches_preflight(ctx):
    """The ambient signal reuses the SAME collapse the pre-flight computes —
    they must never disagree about hand-off readiness."""
    _create(ctx.client, did="p700005")
    leaves = _place_leaf(ctx, "p700005", author="author@sponsor.example")
    ctx.service.record_esign(
        "p700005", _manifest(leaves, signer="qa@sponsor.example"),
        actor="qa@sponsor.example")
    _place_leaf(ctx, "p700005", author="author@sponsor.example",
                body=b"%PDF-1.4 cover REVISED")
    sr = ctx.service.content_state("p700005")["signature_readiness"]
    rep = ctx.service.preflight_report("p700005")
    assert sr["status"] == rep["readiness"]["signature_status"]
    assert sr["handoff_ready"] == rep["readiness"]["handoff_ready_signature"]


def test_signature_readiness_endpoint_content(ctx):
    """The signal ships over the proxy /content endpoint the web state uses."""
    _create(ctx.client, did="p700006")
    r = ctx.client.get("/api/dossier/dossiers/p700006/content")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "signature_readiness" in body
    assert body["signature_readiness"]["needs_resign"] is False
