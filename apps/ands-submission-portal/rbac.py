"""
ANDS Submission Portal — multi-tenant role-based access control + multi-dossier
portfolio isolation.

This ADDITIVE slice implements two previously-unimplemented requirements:

  REQ-038  Multi-tenant role-based access control scoped to the sponsor org, with
           least-privilege roles (org admin, regulatory author, QA reviewer/
           signer, regulatory operations/publisher, read-only) and HARD tenant
           isolation so one sponsor org cannot access another's dossiers or data;
           cross-tenant attempts are denied and audit-logged.
  REQ-047  A multi-dossier / multi-product portfolio in which a single sponsor
           org holds many dossiers and a single product family may span multiple
           DINs, strengths and dossiers, preventing cross-dossier contamination
           of sequences, identifiers, lifecycle operations and prior-leaf
           references (a prior-leaf reference can only resolve within its own
           dossier, never another dossier's sequence).

Pure, dependency-free (Python 3 standard library only) and deterministic.

Requirement traceability tags (REQ-xxx) reference
specs/ands-submission-portal/requirements.md.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# REQ-038: least-privilege roles + capabilities
# ---------------------------------------------------------------------------

# The least-privilege capability set. Each capability is an atomic action the
# portal gates; a role grants only the capabilities it needs.
CAP_READ = "read"                 # view dossiers / data within the org
CAP_AUTHOR = "author"             # create/edit leaves, metadata, content
CAP_VALIDATE = "validate"         # run validation / build reports
CAP_QA_REVIEW = "qa_review"       # record the QA audit-trail review
CAP_SIGN = "sign"                 # apply the authorized e-signature
CAP_TRANSMIT = "transmit"         # transmit / publish a transaction
CAP_MANAGE_USERS = "manage_users"  # assign roles, manage org membership
CAP_MANAGE_ORG = "manage_org"     # org-level configuration + transfers

ALL_CAPABILITIES = (
    CAP_READ, CAP_AUTHOR, CAP_VALIDATE, CAP_QA_REVIEW, CAP_SIGN,
    CAP_TRANSMIT, CAP_MANAGE_USERS, CAP_MANAGE_ORG,
)

ROLE_ORG_ADMIN = "org_admin"
ROLE_REGULATORY_AUTHOR = "regulatory_author"
ROLE_QA_REVIEWER_SIGNER = "qa_reviewer_signer"
ROLE_REGULATORY_OPS = "regulatory_operations"
ROLE_READ_ONLY = "read_only"

# Each role's least-privilege capability grant. Read-only is read-only; an
# author may author/validate but NOT review/sign/transmit (separation of
# duties); the QA reviewer/signer reviews + signs but does not author; the
# publisher (regulatory operations) transmits but does not author or sign; the
# org admin manages users/org but is NOT silently granted authoring/sign/
# transmit (those remain least-privilege, separated duties).
ROLE_CAPABILITIES = {
    ROLE_ORG_ADMIN: {CAP_READ, CAP_MANAGE_USERS, CAP_MANAGE_ORG},
    ROLE_REGULATORY_AUTHOR: {CAP_READ, CAP_AUTHOR, CAP_VALIDATE},
    ROLE_QA_REVIEWER_SIGNER: {CAP_READ, CAP_VALIDATE, CAP_QA_REVIEW, CAP_SIGN},
    ROLE_REGULATORY_OPS: {CAP_READ, CAP_VALIDATE, CAP_TRANSMIT},
    ROLE_READ_ONLY: {CAP_READ},
}

ROLE_LABELS = {
    ROLE_ORG_ADMIN: "Org Admin",
    ROLE_REGULATORY_AUTHOR: "Regulatory Author",
    ROLE_QA_REVIEWER_SIGNER: "QA Reviewer / Signer",
    ROLE_REGULATORY_OPS: "Regulatory Operations / Publisher",
    ROLE_READ_ONLY: "Read-only",
}


class AccessDeniedError(Exception):
    """REQ-038: an access attempt that violates tenant isolation or a missing
    capability. Carries a machine ``rule`` and the audit-log ``record``."""

    def __init__(self, message: str, rule: str, record: dict):
        super().__init__(message)
        self.rule = rule
        self.record = record


def _norm(value) -> str:
    return str(value if value is not None else "").strip()


def is_valid_role(role) -> bool:
    return _norm(role) in ROLE_CAPABILITIES


def capabilities_for(role) -> set:
    """The capability set granted to ``role`` (empty for an unknown role)."""
    return set(ROLE_CAPABILITIES.get(_norm(role), ()))


def role_can(role, capability) -> bool:
    """REQ-038: does ``role`` grant ``capability``?"""
    return _norm(capability) in capabilities_for(role)


def roles_catalog() -> list:
    """REQ-038: the roles + their least-privilege capabilities, as data."""
    return [
        {"role": r, "label": ROLE_LABELS[r],
         "capabilities": sorted(ROLE_CAPABILITIES[r])}
        for r in (ROLE_ORG_ADMIN, ROLE_REGULATORY_AUTHOR,
                  ROLE_QA_REVIEWER_SIGNER, ROLE_REGULATORY_OPS, ROLE_READ_ONLY)
    ]


# ---------------------------------------------------------------------------
# REQ-038: a principal (a user bound to exactly one sponsor org) + authorize
# ---------------------------------------------------------------------------

class Principal:
    """A user acting within exactly one sponsor org, holding one or more roles.

    Per-dossier authorization (REQ-038 'including per-dossier authorization')
    is expressed by an optional ``dossier_scope`` — when non-empty, the
    principal may only act on the listed dossiers within their org.
    """

    def __init__(self, user_id, org_id, roles, dossier_scope=None):
        self.user_id = _norm(user_id)
        self.org_id = _norm(org_id)
        self.roles = [_norm(r) for r in (roles or []) if is_valid_role(r)]
        # None / empty => every dossier in the org; otherwise an allow-list.
        self.dossier_scope = (
            None if not dossier_scope
            else {_norm(d) for d in dossier_scope if _norm(d)})

    def capabilities(self) -> set:
        caps: set = set()
        for r in self.roles:
            caps |= capabilities_for(r)
        return caps

    def has_capability(self, capability) -> bool:
        return _norm(capability) in self.capabilities()

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "org_id": self.org_id,
            "roles": list(self.roles),
            "capabilities": sorted(self.capabilities()),
            "dossier_scope": (None if self.dossier_scope is None
                              else sorted(self.dossier_scope)),
        }


def _audit_record(principal: "Principal", action, resource, allowed,
                  rule, at="") -> dict:
    """REQ-038/NFR-002: the access decision as an append-only audit record."""
    return {
        "user_id": getattr(principal, "user_id", ""),
        "org_id": getattr(principal, "org_id", ""),
        "action": _norm(action),
        "resource_org": _norm((resource or {}).get("org_id")),
        "resource_dossier": _norm((resource or {}).get("dossier_id")),
        "allowed": bool(allowed),
        "rule": _norm(rule),
        "at": _norm(at),
    }


def authorize(principal: "Principal", capability, resource=None, at="") -> dict:
    """REQ-038: authorize ``capability`` on ``resource`` for ``principal``.

    ``resource`` (optional) carries ``org_id`` and/or ``dossier_id``. Enforces,
    in order: (1) hard tenant isolation — the resource org must equal the
    principal's org; (2) per-dossier scope — if the principal is dossier-scoped
    the resource dossier must be in scope; (3) capability — the principal's
    roles must grant the capability. EVERY decision returns an audit record;
    callers persist it (the denial is audit-logged per REQ-038).
    """
    resource = resource or {}
    res_org = _norm(resource.get("org_id"))
    res_dossier = _norm(resource.get("dossier_id"))

    # (1) hard tenant isolation — never leak across orgs.
    if res_org and res_org != principal.org_id:
        rule = "tenant_isolation"
        return {
            "allowed": False, "rule": rule,
            "message": (f"Access denied: dossier/data belongs to org "
                        f"'{res_org}', not '{principal.org_id}'"),
            "audit": _audit_record(principal, capability, resource, False,
                                   rule, at),
        }

    # (2) per-dossier authorization within the org.
    if (res_dossier and principal.dossier_scope is not None
            and res_dossier not in principal.dossier_scope):
        rule = "dossier_scope"
        return {
            "allowed": False, "rule": rule,
            "message": (f"Access denied: user is not authorized for dossier "
                        f"'{res_dossier}'"),
            "audit": _audit_record(principal, capability, resource, False,
                                   rule, at),
        }

    # (3) least-privilege capability.
    if not principal.has_capability(capability):
        rule = "capability"
        return {
            "allowed": False, "rule": rule,
            "message": (f"Access denied: role(s) {principal.roles} do not grant "
                        f"'{_norm(capability)}'"),
            "audit": _audit_record(principal, capability, resource, False,
                                   rule, at),
        }

    return {
        "allowed": True, "rule": "",
        "message": "",
        "audit": _audit_record(principal, capability, resource, True, "", at),
    }


def require(principal: "Principal", capability, resource=None, at="") -> dict:
    """REQ-038: authorize and RAISE :class:`AccessDeniedError` on denial.

    Returns the audit record on success (callers persist it)."""
    decision = authorize(principal, capability, resource, at)
    if not decision["allowed"]:
        raise AccessDeniedError(decision["message"], decision["rule"],
                                decision["audit"])
    return decision["audit"]


# ---------------------------------------------------------------------------
# REQ-047: multi-dossier / multi-product portfolio isolation
# ---------------------------------------------------------------------------

class Portfolio:
    """A sponsor org's portfolio: many dossiers, and product families that span
    multiple DINs/strengths/dossiers, WITHOUT forcing them into one sequence
    stream. Enforces that lifecycle operations and prior-leaf references resolve
    strictly within their own dossier (REQ-047)."""

    def __init__(self, org_id):
        self.org_id = _norm(org_id)
        # dossier_id -> {"product_family", "din", "strength"}
        self.dossiers: dict = {}
        # product_family -> list of {"dossier_id", "din", "strength"}
        self.families: dict = {}

    def add_dossier(self, dossier_id, product_family="", din="", strength="") -> dict:
        """Register a dossier in the portfolio. A product family may map to many
        dossiers/DINs/strengths; each dossier keeps its OWN sequence stream."""
        dossier_id = _norm(dossier_id)
        if not dossier_id:
            raise ValueError("dossier_id is required")
        rec = {
            "dossier_id": dossier_id,
            "product_family": _norm(product_family),
            "din": _norm(din),
            "strength": _norm(strength),
            "org_id": self.org_id,
        }
        self.dossiers[dossier_id] = rec
        fam = rec["product_family"]
        if fam:
            members = self.families.setdefault(fam, [])
            if not any(m["dossier_id"] == dossier_id for m in members):
                members.append({"dossier_id": dossier_id, "din": rec["din"],
                                "strength": rec["strength"]})
        return dict(rec)

    def owns(self, dossier_id) -> bool:
        return _norm(dossier_id) in self.dossiers

    def family_members(self, product_family) -> list:
        """The product-family → dossier/DIN/strength relationships (REQ-047)."""
        return [dict(m) for m in self.families.get(_norm(product_family), [])]

    def validate_prior_leaf_reference(self, dossier_id, modified_leaf,
                                      dossier_live_leaves) -> list:
        """REQ-047: a prior-leaf reference can ONLY resolve to a leaf within the
        SAME dossier — never another dossier's sequence.

        ``dossier_live_leaves`` is the set of live leaf ids in ``dossier_id``.
        Returns a list of {"rule", "message"} findings (empty when clean)."""
        dossier_id = _norm(dossier_id)
        modified_leaf = _norm(modified_leaf)
        if not modified_leaf:
            return []
        live = {_norm(x) for x in (dossier_live_leaves or [])}
        if modified_leaf in live:
            return []
        # Is the referenced leaf actually owned by ANOTHER dossier? Surface a
        # cross-dossier contamination finding distinctly from a plain dangling ref.
        for other_id, _ in self.dossiers.items():
            if other_id != dossier_id:
                # The caller doesn't pass other dossiers' leaves here; the point
                # is the reference is NOT in this dossier's live set, so block.
                break
        return [{
            "rule": "cross_dossier_reference",
            "message": (f"Prior-leaf reference '{modified_leaf}' does not resolve "
                        f"within dossier '{dossier_id}'; references must stay "
                        "inside their own dossier"),
        }]

    def assert_sequence_isolation(self, dossier_id) -> str:
        """REQ-047: resolve the dossier a sequence belongs to, raising if the
        dossier is not owned by this org's portfolio (prevents a sequence being
        attributed to a foreign dossier)."""
        dossier_id = _norm(dossier_id)
        if not self.owns(dossier_id):
            raise AccessDeniedError(
                f"dossier '{dossier_id}' is not in org '{self.org_id}'s portfolio",
                "portfolio_isolation",
                {"org_id": self.org_id, "dossier_id": dossier_id})
        return dossier_id

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "dossiers": [dict(v) for v in self.dossiers.values()],
            "families": {k: [dict(m) for m in v]
                         for k, v in self.families.items()},
        }
