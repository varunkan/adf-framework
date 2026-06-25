"""
ANDS Submission Portal — approval gate + tamper-evident electronic-signature
manifest, anchored to the HPFB Electronic Signatures Policy.

This ADDITIVE slice implements three previously-unimplemented requirements:

  REQ-039  An approval gate where a QA reviewer performs a documented
           audit-trail review and an authorized signer applies an electronic
           signature BEFORE transmission becomes available, anchored to the
           HPFB Electronic Signatures Policy (case-by-case HC acceptance). The
           Annex-11/ALCOA+ control set is a VALUE-ADD best practice, NOT an HC
           mandate.
  REQ-053  Every applied signature is bound to an IMMUTABLE signature manifest
           recording the exact artifact + its checksum AT signing time, the
           signer identity + auth method, the signing timestamp + timezone, and
           the signature meaning; any post-signature modification of the signed
           content is detected and flagged (re-blocking transmission). VALUE-ADD
           integrity control.
  REQ-068  Anchor e-signature handling to the HPFB Electronic Signatures Policy
           and provide a workflow to request + record case-by-case HC acceptance
           (hc.cesg-pcde.sc@canada.ca), rather than asserting a self-imposed
           Part-11/Annex-11 mandate.

Pure, dependency-free (Python 3 standard library only) and deterministic:
timestamps are supplied by the caller so signing/verification is reproducible.

Requirement traceability tags (REQ-xxx) reference
specs/ands-submission-portal/requirements.md.
"""

from __future__ import annotations

import hashlib


# REQ-039 / REQ-068: the governing artifact is the HPFB Electronic Signatures
# Policy — HC accepts e-signatures on submission content CASE-BY-CASE; this is a
# permission, not a mandated Part-11/Annex-11 control set.
HPFB_POLICY = {
    "name": "HPFB Electronic Signatures Policy",
    "acceptance": "case-by-case",
    "request_contact": "hc.cesg-pcde.sc@canada.ca",
    "basis": "value-add",
    "note": ("HC accepts e-signatures on submission content case-by-case under "
             "the HPFB Electronic Signatures Policy. The Annex-11/ALCOA+ "
             "control set here is a value-add best practice, not an HC mandate."),
}

# REQ-039: least-privilege sign-off roles. Only a QA reviewer may record the
# audit-trail review; only an authorized signer may apply the signature.
ROLE_QA_REVIEWER = "qa_reviewer"
ROLE_SIGNER = "authorized_signer"

# The recognised signature meanings (controlled vocabulary).
SIGNATURE_MEANINGS = ("approved", "reviewed", "authored", "authorized")


def _norm(value) -> str:
    return str(value if value is not None else "").strip()


def artifact_checksum(content) -> str:
    """The MD5 hex of an artifact's bytes (mirrors ectd checksum-type MD5)."""
    if isinstance(content, bytes):
        data = content
    else:
        data = _norm(content).encode("utf-8")
    return hashlib.md5(data).hexdigest()


def policy() -> dict:
    """REQ-039 / REQ-068: the HPFB policy descriptor as data."""
    return dict(HPFB_POLICY)


# ---------------------------------------------------------------------------
# REQ-068: case-by-case HC acceptance workflow
# ---------------------------------------------------------------------------

def request_hc_acceptance(data: dict) -> dict:
    """REQ-068: build a request to capture HC's case-by-case acceptance of a
    given e-signature approach, and a record to store the acceptance.

    ``data`` carries the ``approach`` description and the requesting
    ``org``/``sponsor``. Returns a request envelope addressed to HC's contact
    plus an ``acceptance`` stub the caller persists once HC responds.
    """
    data = data or {}
    approach = _norm(data.get("approach"))
    org = _norm(data.get("org") or data.get("sponsor"))
    errors = []
    if not approach:
        errors.append({"rule": "approach_required",
                       "message": "An e-signature approach description is "
                                  "required"})
    if not org:
        errors.append({"rule": "org_required",
                       "message": "The requesting sponsor org is required"})
    if errors:
        return {"valid": False, "errors": errors}
    return {
        "valid": True,
        "request": {
            "to": HPFB_POLICY["request_contact"],
            "policy": HPFB_POLICY["name"],
            "org": org,
            "approach": approach,
            "status": "pending",
        },
        "policy": dict(HPFB_POLICY),
    }


def record_hc_acceptance(data: dict) -> dict:
    """REQ-068: record HC's decision on a requested e-signature approach."""
    data = data or {}
    approach = _norm(data.get("approach"))
    accepted = bool(data.get("accepted"))
    if not approach:
        return {"valid": False, "errors": [
            {"rule": "approach_required",
             "message": "An e-signature approach is required"}]}
    return {
        "valid": True,
        "acceptance": {
            "approach": approach,
            "accepted": accepted,
            "org": _norm(data.get("org") or data.get("sponsor")),
            "reference": _norm(data.get("reference")),
            "at": _norm(data.get("at")),
            "policy": HPFB_POLICY["name"],
        },
    }


# ---------------------------------------------------------------------------
# REQ-039: QA audit-trail review
# ---------------------------------------------------------------------------

def qa_review(data: dict) -> dict:
    """REQ-039: record a QA reviewer's documented audit-trail review sign-off.

    ``data`` carries the ``reviewer`` identity, their ``role`` (must be the QA
    reviewer role), the reviewed ``artifact`` ids, an ``audit_trail_reviewed``
    flag, and the review ``at`` timestamp. Returns ``{"valid", "review"|errors}``.
    """
    data = data or {}
    errors = []
    reviewer = _norm(data.get("reviewer"))
    role = _norm(data.get("role")) or ROLE_QA_REVIEWER
    if not reviewer:
        errors.append({"rule": "reviewer_required",
                       "message": "A named QA reviewer is required"})
    if role != ROLE_QA_REVIEWER:
        errors.append({"rule": "role_not_permitted",
                       "message": (f"Only a '{ROLE_QA_REVIEWER}' may record the "
                                   "audit-trail review")})
    if not bool(data.get("audit_trail_reviewed")):
        errors.append({"rule": "audit_trail_not_reviewed",
                       "message": "The audit-trail review must be confirmed"})
    if errors:
        return {"valid": False, "errors": errors}
    return {
        "valid": True,
        "review": {
            "reviewer": reviewer,
            "role": ROLE_QA_REVIEWER,
            "audit_trail_reviewed": True,
            "at": _norm(data.get("at")),
            "comment": _norm(data.get("comment")),
        },
    }


# ---------------------------------------------------------------------------
# REQ-053: signature manifest binding + tamper detection
# ---------------------------------------------------------------------------

def sign(data: dict) -> dict:
    """REQ-039 / REQ-053: apply an electronic signature and emit an immutable
    signature manifest.

    ``data`` carries the ``signer`` identity, their ``role`` (must be the signer
    role), the ``auth_method`` used to (re-)authenticate at signing, the
    ``meaning`` (controlled vocabulary), the signing ``at`` timestamp + ``tz``,
    and the ``artifacts`` being signed — each ``{"id", "kind", "content"|"checksum"}``.
    The manifest records each artifact's checksum AT signing time so a later
    modification is detectable. Returns ``{"valid", "manifest"|errors}``.
    """
    data = data or {}
    errors = []
    signer = _norm(data.get("signer"))
    role = _norm(data.get("role")) or ROLE_SIGNER
    meaning = _norm(data.get("meaning")) or "approved"
    auth_method = _norm(data.get("auth_method"))
    if not signer:
        errors.append({"rule": "signer_required",
                       "message": "An authorized signer identity is required"})
    if role != ROLE_SIGNER:
        errors.append({"rule": "role_not_permitted",
                       "message": (f"Only an '{ROLE_SIGNER}' may apply the "
                                   "signature")})
    if not auth_method:
        errors.append({"rule": "auth_method_required",
                       "message": "The signer must (re-)authenticate at signing "
                                  "— an auth method is required"})
    if meaning not in SIGNATURE_MEANINGS:
        errors.append({"rule": "meaning_invalid",
                       "message": (f"Signature meaning must be one of "
                                   f"{', '.join(SIGNATURE_MEANINGS)}")})
    artifacts = data.get("artifacts") or []
    if not artifacts:
        errors.append({"rule": "artifacts_required",
                       "message": "At least one artifact must be signed"})

    bound = []
    for art in artifacts:
        if not isinstance(art, dict):
            errors.append({"rule": "artifact_invalid",
                           "message": "Each artifact must be an object"})
            continue
        art_id = _norm(art.get("id"))
        if not art_id:
            errors.append({"rule": "artifact_id_required",
                           "message": "Each signed artifact needs an id"})
            continue
        checksum = _norm(art.get("checksum"))
        if not checksum and "content" in art:
            checksum = artifact_checksum(art.get("content"))
        if not checksum:
            errors.append({"rule": "artifact_checksum_required",
                           "message": (f"Artifact '{art_id}' needs content or a "
                                       "checksum to bind the signature")})
            continue
        bound.append({
            "id": art_id,
            "kind": _norm(art.get("kind")) or "leaf",
            "checksum": checksum,
            "checksum_type": "MD5",
        })

    if errors:
        return {"valid": False, "errors": errors}

    manifest = {
        "signer": signer,
        "role": ROLE_SIGNER,
        "auth_method": auth_method,
        "meaning": meaning,
        "at": _norm(data.get("at")),
        "tz": _norm(data.get("tz")) or "UTC",
        "artifacts": bound,
        "policy": HPFB_POLICY["name"],
        "basis": HPFB_POLICY["basis"],
        "immutable": True,
    }
    # A stable fingerprint over the bound artifacts (order-independent) gives the
    # manifest its own tamper-evident id.
    digest_src = "|".join(sorted(f"{a['id']}:{a['checksum']}" for a in bound))
    manifest["manifest_id"] = hashlib.md5(digest_src.encode("utf-8")).hexdigest()
    return {"valid": True, "manifest": manifest}


def verify_manifest(manifest: dict, current) -> dict:
    """REQ-053: detect any post-signature modification of the signed content.

    ``manifest`` is a manifest emitted by :func:`sign`; ``current`` maps each
    artifact id to its CURRENT checksum (or to ``{"checksum"|"content"}``).
    Returns ``{"valid", "tampered", "findings"}`` — ``valid`` False (and the
    signature invalidated) on any mismatch or missing artifact.
    """
    manifest = manifest or {}
    current = _current_checksums(current)
    findings = []
    for art in manifest.get("artifacts") or []:
        art_id = _norm(art.get("id"))
        signed = _norm(art.get("checksum"))
        now = current.get(art_id)
        if now is None:
            findings.append({
                "rule": "signed_artifact_missing",
                "artifact": art_id,
                "message": (f"Signed artifact '{art_id}' is no longer present — "
                            "the signature is invalidated"),
            })
        elif now != signed:
            findings.append({
                "rule": "signed_content_modified",
                "artifact": art_id,
                "signed_checksum": signed,
                "current_checksum": now,
                "message": (f"Artifact '{art_id}' was modified after signing — "
                            "the signature is invalidated"),
            })
    tampered = bool(findings)
    return {
        "valid": not tampered,
        "tampered": tampered,
        "findings": findings,
        "manifest_id": _norm(manifest.get("manifest_id")),
    }


def _current_checksums(current) -> dict:
    """Normalise ``current`` into {id: checksum}."""
    out: dict = {}
    if isinstance(current, dict):
        items = current.items()
    else:
        items = [(c.get("id"), c) for c in (current or [])
                 if isinstance(c, dict)]
    for key, val in items:
        art_id = _norm(key)
        if not art_id:
            continue
        if isinstance(val, dict):
            checksum = _norm(val.get("checksum"))
            if not checksum and "content" in val:
                checksum = artifact_checksum(val.get("content"))
        else:
            checksum = _norm(val)
        out[art_id] = checksum
    return out


# ---------------------------------------------------------------------------
# REQ-039: the transmission approval gate
# ---------------------------------------------------------------------------

def transmission_gate(data: dict) -> dict:
    """REQ-039 / REQ-053: transmission becomes available only after a documented
    QA audit-trail review AND a valid, untampered authorized signature.

    ``data`` carries ``review`` (from :func:`qa_review`), ``manifest`` (from
    :func:`sign`), and optionally ``current`` checksums to re-verify the
    manifest at gate time (REQ-053: post-sign tampering re-blocks). Returns
    ``{"can_transmit", "blockers", "qa_reviewed", "signed", "tampered"}``.
    """
    data = data or {}
    review = data.get("review") or {}
    manifest = data.get("manifest") or {}
    blockers = []

    qa_reviewed = bool(review.get("audit_trail_reviewed")) and \
        _norm(review.get("reviewer")) != ""
    if not qa_reviewed:
        blockers.append({
            "rule": "qa_review_missing",
            "message": "A documented QA audit-trail review is required before "
                       "transmission",
        })

    signed = bool(manifest.get("artifacts")) and \
        _norm(manifest.get("signer")) != ""
    if not signed:
        blockers.append({
            "rule": "signature_missing",
            "message": "An authorized e-signature is required before "
                       "transmission",
        })

    tampered = False
    if signed and "current" in data:
        verdict = verify_manifest(manifest, data.get("current"))
        tampered = verdict["tampered"]
        if tampered:
            blockers.extend(verdict["findings"])

    return {
        "can_transmit": not blockers,
        "qa_reviewed": qa_reviewed,
        "signed": signed,
        "tampered": tampered,
        "blockers": blockers,
        "policy": HPFB_POLICY["name"],
    }
