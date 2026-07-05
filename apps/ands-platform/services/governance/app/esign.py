"""E-signature domain — pure (ported verbatim from the monolith ``esign``).

HPFB-policy-anchored: QA audit-trail review + an immutable, tamper-evident
signature manifest gate transmission (REQ-039/053/068).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

HPFB_POLICY = {
    "name": "HPFB Electronic Signatures Policy", "acceptance": "case-by-case",
    "request_contact": "hc.cesg-pcde.sc@canada.ca", "basis": "value-add",
    "note": ("HC accepts e-signatures on submission content case-by-case under "
             "the HPFB Electronic Signatures Policy. The Annex-11/ALCOA+ control "
             "set here is a value-add best practice, not an HC mandate.")}

ROLE_QA_REVIEWER = "qa_reviewer"
ROLE_SIGNER = "authorized_signer"
SIGNATURE_MEANINGS = ("approved", "reviewed", "authored", "authorized")

# Human, meaning-of-signature statements per controlled meaning — used as the
# default signing REASON when a caller (e.g. the in-process mesh) does not
# supply its own attestation text. A 21 CFR Part 11 e-signature must carry the
# MEANING of the signing; this makes that meaning explicit and legible.
_MEANING_STATEMENTS = {
    "approved": "I approve this submission package and authorize its transmission.",
    "reviewed": "I have reviewed this submission package.",
    "authored": "I am the author of this submission content.",
    "authorized": "I authorize the transmission of this submission package.",
}


def _norm(value) -> str:
    return str(value if value is not None else "").strip()


def _ident(value) -> str:
    """Normalize an identity for COMPARISON: an email/username that differs only
    by case or surrounding whitespace is the same person, so SoD cannot be
    defeated by 'Vera@X' vs 'vera@x'. Not used for display — only for equality."""
    return _norm(value).lower()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def artifact_checksum(content) -> str:
    data = content if isinstance(content, bytes) else _norm(content).encode("utf-8")
    return hashlib.md5(data).hexdigest()


def policy() -> dict:
    return dict(HPFB_POLICY)


def request_hc_acceptance(data: dict) -> dict:
    data = data or {}
    approach = _norm(data.get("approach"))
    org = _norm(data.get("org") or data.get("sponsor"))
    errors = []
    if not approach:
        errors.append({"rule": "approach_required",
                       "message": "An e-signature approach description is required"})
    if not org:
        errors.append({"rule": "org_required",
                       "message": "The requesting sponsor org is required"})
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "request": {
        "to": HPFB_POLICY["request_contact"], "policy": HPFB_POLICY["name"],
        "org": org, "approach": approach, "status": "pending"},
        "policy": dict(HPFB_POLICY)}


def record_hc_acceptance(data: dict) -> dict:
    data = data or {}
    approach = _norm(data.get("approach"))
    if not approach:
        return {"valid": False, "errors": [
            {"rule": "approach_required",
             "message": "An e-signature approach is required"}]}
    return {"valid": True, "acceptance": {
        "approach": approach, "accepted": bool(data.get("accepted")),
        "org": _norm(data.get("org") or data.get("sponsor")),
        "reference": _norm(data.get("reference")), "at": _norm(data.get("at")),
        "policy": HPFB_POLICY["name"]}}


def qa_review(data: dict) -> dict:
    data = data or {}
    errors = []
    reviewer = _norm(data.get("reviewer"))
    role = _norm(data.get("role")) or ROLE_QA_REVIEWER
    if not reviewer:
        errors.append({"rule": "reviewer_required",
                       "message": "A named QA reviewer is required"})
    if role != ROLE_QA_REVIEWER:
        errors.append({"rule": "role_not_permitted",
                       "message": f"Only a '{ROLE_QA_REVIEWER}' may record the "
                                  "audit-trail review"})
    if not bool(data.get("audit_trail_reviewed")):
        errors.append({"rule": "audit_trail_not_reviewed",
                       "message": "The audit-trail review must be confirmed"})
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "review": {
        "reviewer": reviewer, "role": ROLE_QA_REVIEWER,
        "audit_trail_reviewed": True, "at": _norm(data.get("at")),
        "comment": _norm(data.get("comment"))}}


def segregation_of_duties(signer, authors) -> dict:
    """TIER2-ROLE-SEP: a segregation-of-duties check for a Part-11 e-signature.

    An e-signature is only DEFENSIBLE when the person attesting/approving is a
    DISTINCT authorized approver — not one of the authors of the very content
    being signed. This compares the SIGNER identity against the set of AUTHOR
    identities recorded for the signed content and reports:

      - ``conflict``            the signer is (also) one of the authors;
      - ``conflicting_authors`` the display identities that collide (deduped);
      - ``authorship_known``    whether ANY author identity was recorded — with
                                no author on record we cannot PROVE separation,
                                so ``separated`` is False and this stays False.
                                We never silently report unknown authorship as
                                cleanly separated.

    Honesty: this asserts that "the signer attests as a distinct approver". It
    is NOT an SSO/IdP identity assertion — the identities are the recorded
    signer/author strings, compared case/whitespace-insensitively.
    """
    signer_key = _ident(signer)
    # dedupe authors on the comparison key while keeping the first display form
    by_key: dict[str, str] = {}
    for a in (authors or []):
        key = _ident(a)
        if key and key not in by_key:
            by_key[key] = _norm(a)
    authorship_known = bool(by_key)
    conflicting = [display for key, display in by_key.items()
                   if key and key == signer_key]
    conflict = bool(conflicting)
    # separation is PROVEN only when authorship is known AND no author collides
    separated = authorship_known and not conflict
    reason = ("The signer is also an author of the content being signed — a "
              "segregation-of-duties conflict. A 21 CFR Part 11 signature is "
              "most defensible when the signer is a DISTINCT authorized "
              "approver from the author(s)." if conflict else
              ("The signer is distinct from all recorded author(s) of the "
               "signed content." if separated else
               "No author identity is recorded for the signed content, so "
               "separation of duties cannot be proven from the record."))
    return {
        "separated": separated, "conflict": conflict,
        "authorship_known": authorship_known,
        "signer": _norm(signer),
        "authors": list(by_key.values()),
        "author_count": len(by_key),
        "conflicting_authors": conflicting,
        "reason": reason,
    }


def sign(data: dict) -> dict:
    data = data or {}
    errors = []
    signer = _norm(data.get("signer"))
    role = _norm(data.get("role")) or ROLE_SIGNER
    meaning = _norm(data.get("meaning")) or "approved"
    auth_method = _norm(data.get("auth_method"))
    # The signing REASON is the human meaning-of-signature statement (Part-11).
    # When the caller omits the key entirely we default it from the controlled
    # meaning (keeps the in-process mesh working); when the caller SUPPLIES the
    # key but leaves it blank, that is a rejected signature — an explicit
    # e-signature must carry its meaning.
    if "reason" in data:
        reason = _norm(data.get("reason"))
        if not reason:
            errors.append({"rule": "reason_required",
                           "message": "A signing reason (the meaning of the "
                                      "signature) is required"})
    else:
        reason = _MEANING_STATEMENTS.get(meaning, _MEANING_STATEMENTS["approved"])
    if not signer:
        errors.append({"rule": "signer_required",
                       "message": "An authorized signer identity is required"})
    if role != ROLE_SIGNER:
        errors.append({"rule": "role_not_permitted",
                       "message": f"Only an '{ROLE_SIGNER}' may apply the signature"})
    if not auth_method:
        errors.append({"rule": "auth_method_required",
                       "message": "The signer must (re-)authenticate at signing"})
    if meaning not in SIGNATURE_MEANINGS:
        errors.append({"rule": "meaning_invalid",
                       "message": "Signature meaning must be one of "
                                  + ", ".join(SIGNATURE_MEANINGS)})
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
                           "message": f"Artifact '{art_id}' needs content or a "
                                      "checksum to bind the signature"})
            continue
        bound.append({"id": art_id, "kind": _norm(art.get("kind")) or "leaf",
                      "checksum": checksum, "checksum_type": "MD5"})
    # TIER2-ROLE-SEP: segregation of duties. The signer must be a DISTINCT
    # authorized approver from the author(s) of the content being signed. The
    # default posture SURFACES + WARNS (recording the outcome on the manifest);
    # an admin may make it a HARD BLOCK per tenant via ``enforce_segregation``.
    enforce_sod = bool(data.get("enforce_segregation"))
    sod = segregation_of_duties(signer, data.get("authors") or [])
    sod = {**sod, "enforced": enforce_sod}
    if enforce_sod and sod["conflict"]:
        errors.append({
            "rule": "segregation_of_duties",
            "message": ("Segregation of duties is required: the signer "
                        f"({signer}) is also an author of the content being "
                        "signed. A distinct authorized approver must apply "
                        "this signature.")})
    if errors:
        return {"valid": False, "errors": errors}
    manifest = {
        "segregation_of_duties": sod,
        "signer": signer, "role": ROLE_SIGNER, "auth_method": auth_method,
        "meaning": meaning, "reason": reason,
        # server-stamped UTC when the caller does not supply one, so the
        # signing time is a trustworthy record and never blank
        "at": _norm(data.get("at")) or _utcnow_iso(),
        "tz": _norm(data.get("tz")) or "UTC", "artifacts": bound,
        "leaf_count": len(bound),
        "policy": HPFB_POLICY["name"], "basis": HPFB_POLICY["basis"],
        "immutable": True}
    digest_src = "|".join(sorted(f"{a['id']}:{a['checksum']}" for a in bound))
    manifest["manifest_id"] = hashlib.md5(digest_src.encode("utf-8")).hexdigest()
    return {"valid": True, "manifest": manifest}


def _current_checksums(current) -> dict:
    out: dict = {}
    items = current.items() if isinstance(current, dict) else [
        (c.get("id"), c) for c in (current or []) if isinstance(c, dict)]
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


def verify_manifest(manifest: dict, current) -> dict:
    manifest = manifest or {}
    current = _current_checksums(current)
    findings = []
    for art in manifest.get("artifacts") or []:
        art_id = _norm(art.get("id"))
        signed = _norm(art.get("checksum"))
        now = current.get(art_id)
        if now is None:
            findings.append({"rule": "signed_artifact_missing", "artifact": art_id,
                             "message": f"Signed artifact '{art_id}' is no longer "
                                        "present — the signature is invalidated"})
        elif now != signed:
            findings.append({"rule": "signed_content_modified", "artifact": art_id,
                             "signed_checksum": signed, "current_checksum": now,
                             "message": f"Artifact '{art_id}' was modified after "
                                        "signing — the signature is invalidated"})
    tampered = bool(findings)
    return {"valid": not tampered, "tampered": tampered, "findings": findings,
            "manifest_id": _norm(manifest.get("manifest_id"))}


def transmission_gate(data: dict) -> dict:
    data = data or {}
    review = data.get("review") or {}
    manifest = data.get("manifest") or {}
    blockers = []
    qa_reviewed = bool(review.get("audit_trail_reviewed")) and \
        _norm(review.get("reviewer")) != ""
    if not qa_reviewed:
        blockers.append({"rule": "qa_review_missing",
                         "message": "A documented QA audit-trail review is "
                                    "required before transmission"})
    signed = bool(manifest.get("artifacts")) and _norm(manifest.get("signer")) != ""
    if not signed:
        blockers.append({"rule": "signature_missing",
                         "message": "An authorized e-signature is required before "
                                    "transmission"})
    tampered = False
    if signed and "current" in data:
        verdict = verify_manifest(manifest, data.get("current"))
        tampered = verdict["tampered"]
        if tampered:
            blockers.extend(verdict["findings"])
    return {"can_transmit": not blockers, "qa_reviewed": qa_reviewed,
            "signed": signed, "tampered": tampered, "blockers": blockers,
            "policy": HPFB_POLICY["name"]}
