"""TIER2-ROLE-SEP: segregation of duties — the e-signer must be a DISTINCT
authorized approver, not one of the authors of the content being signed
(21 CFR Part 11 / GxP defensibility). Pure-domain proof.

Grounding: the e-sign domain already binds a manifest over the checksummed
eCTD leaves. Each signed artifact can carry the identity/-ies that AUTHORED it
(content_origin author on the dossier side). SoD compares the SIGNER identity
against that author set. Honesty: this is a role-SEPARATION check ("the signer
attests as a distinct approver"), NOT an SSO/IdP identity claim.
"""

from app import esign


# --- the pure SoD check -----------------------------------------------------

def test_sod_conflict_when_signer_is_an_author():
    res = esign.segregation_of_duties(
        signer="vera@sponsor.example",
        authors=["vera@sponsor.example", "amir@sponsor.example"])
    assert res["separated"] is False
    assert res["conflict"] is True
    # the conflicting identity is named so the UI can show exactly who
    assert res["conflicting_authors"] == ["vera@sponsor.example"]
    assert "reason" in res


def test_sod_clean_when_signer_distinct_from_all_authors():
    res = esign.segregation_of_duties(
        signer="qa@sponsor.example",
        authors=["vera@sponsor.example", "amir@sponsor.example"])
    assert res["separated"] is True
    assert res["conflict"] is False
    assert res["conflicting_authors"] == []


def test_sod_is_case_and_whitespace_insensitive_on_identity():
    # a signer that differs only by case/whitespace is still the SAME person —
    # SoD must not be defeated by "Vera@Sponsor.Example" vs "vera@sponsor.example"
    res = esign.segregation_of_duties(
        signer="  Vera@Sponsor.Example ",
        authors=["vera@sponsor.example"])
    assert res["conflict"] is True
    assert res["conflicting_authors"] == ["vera@sponsor.example"]


def test_sod_unknown_authorship_is_surfaced_not_silently_passed():
    # when NO author identity is recorded we cannot prove separation — this is
    # surfaced as unknown (separated stays False-ish but not a hard conflict),
    # never silently reported as clean.
    res = esign.segregation_of_duties(signer="vera@x", authors=[])
    assert res["conflict"] is False
    assert res["separated"] is False
    assert res["authorship_known"] is False


def test_sod_dedupes_and_ignores_blank_authors():
    res = esign.segregation_of_duties(
        signer="qa@x",
        authors=["amir@x", "amir@x", "", None, "  "])
    assert res["separated"] is True
    assert res["author_count"] == 1


# --- sign() integrates SoD onto the manifest --------------------------------

def test_sign_records_sod_outcome_on_manifest_clean():
    res = esign.sign({
        "signer": "qa@sponsor.example", "auth_method": "mfa",
        "meaning": "approved", "authors": ["amir@sponsor.example"],
        "artifacts": [{"id": "l1", "content": "a"}]})
    assert res["valid"]
    sod = res["manifest"]["segregation_of_duties"]
    assert sod["separated"] is True and sod["conflict"] is False


def test_sign_soft_warns_by_default_when_signer_is_author():
    # default posture: SURFACE + WARN (a typed-email signer might legitimately be
    # a co-author in a small shop) — the signature is still produced, but the
    # SoD conflict is recorded on the manifest for the Part-11 trail.
    res = esign.sign({
        "signer": "vera@sponsor.example", "auth_method": "mfa",
        "meaning": "approved", "authors": ["vera@sponsor.example"],
        "artifacts": [{"id": "l1", "content": "a"}]})
    assert res["valid"] is True
    sod = res["manifest"]["segregation_of_duties"]
    assert sod["conflict"] is True
    assert sod["enforced"] is False
    assert sod["conflicting_authors"] == ["vera@sponsor.example"]


def test_sign_hard_blocks_when_admin_enforces_sod():
    # admin-configurable HARD BLOCK: the signer being an author is a rejected
    # signature — segregation of duties is mandatory for this tenant.
    res = esign.sign({
        "signer": "vera@sponsor.example", "auth_method": "mfa",
        "meaning": "approved", "authors": ["vera@sponsor.example"],
        "enforce_segregation": True,
        "artifacts": [{"id": "l1", "content": "a"}]})
    assert res["valid"] is False
    assert "segregation_of_duties" in {e["rule"] for e in res["errors"]}


def test_sign_enforced_but_separated_still_signs():
    res = esign.sign({
        "signer": "qa@sponsor.example", "auth_method": "mfa",
        "meaning": "approved", "authors": ["vera@sponsor.example"],
        "enforce_segregation": True,
        "artifacts": [{"id": "l1", "content": "a"}]})
    assert res["valid"] is True
    assert res["manifest"]["segregation_of_duties"]["enforced"] is True
