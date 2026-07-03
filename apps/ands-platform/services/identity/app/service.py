"""Identity application service — auth, tenancy, entitlements, RBAC use-cases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ands_shared import EventEnvelope, EventType, ProblemError, new_id

from . import billing, entitlements, rbac, security
from .ports import IdentityRepository

PLATFORM_TENANT = ""          # owner accounts live outside any tenant
SESSION_TTL = timedelta(hours=12)
# a member locked out by a workspace MFA mandate gets a short-lived token that
# only carries them through enrolment; they must re-login with a code after.
MFA_SETUP_TTL = timedelta(minutes=15)
TENANT_TRIAL = "trial"
TENANT_ACTIVE = "active"
TENANT_SUSPENDED = "suspended"


def _s(v) -> str:
    return str(v or "").strip()


def _email(v) -> str:
    return _s(v).lower()


PASSWORD_POLICY = ("Password must be at least 10 characters and include "
                   "both letters and numbers.")
RESET_CODE_TTL = timedelta(minutes=15)


def _check_password_policy(password: str) -> None:
    pw = password or ""
    if (len(pw) < 10 or not any(c.isalpha() for c in pw)
            or not any(c.isdigit() for c in pw)):
        raise ProblemError(422, PASSWORD_POLICY, rule="password_policy")


class IdentityService:
    def __init__(self, repo: IdentityRepository, bus,
                 *, source: str = "identity") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    def register(self) -> "IdentityService":
        return self

    # -- bootstrap ----------------------------------------------------------
    def ensure_owner(self, email: str, password: str) -> dict:
        existing = self.repo.get_by_email_raw(PLATFORM_TENANT, _email(email))
        if existing:
            return self.repo._public(existing)
        return self._add_user(PLATFORM_TENANT, email, password,
                              rbac.OWNER_ROLE, "Platform Owner")

    # -- internal user creation --------------------------------------------
    def _add_user(self, tenant_id, email, password, role, name) -> dict:
        email = _email(email)
        if not email or "@" not in email:
            raise ProblemError(422, "a valid email is required",
                               rule="email_invalid")
        if role not in rbac.ROLES:
            raise ProblemError(422, f"unknown role: {role}", rule="role_invalid")
        try:
            salt, pw_hash = security.hash_password(password)
        except ValueError:
            raise ProblemError(422, "password is required",
                               rule="password_required")
        try:
            return self.repo.create_user(tenant_id, email, salt, pw_hash, role,
                                         name)
        except ValueError as exc:
            raise ProblemError(409, str(exc), rule="user_exists")

    # -- signup / login / session ------------------------------------------
    def signup(self, data: dict) -> dict:
        """Self-serve: create a tenant (trial, all-features) + its admin user +
        a session (REQ-077)."""
        _check_password_policy(_s(data.get("password")))
        company = _s(data.get("company_name")) or "New tenant"
        tenant_id = new_id()
        tenant = self.repo.create_tenant(
            tenant_id, company, entitlements.DEFAULT_PLAN_ID, TENANT_TRIAL)
        user = self._add_user(tenant_id, data.get("email"),
                              data.get("password"), rbac.TENANT_ADMIN_ROLE,
                              _s(data.get("name")))
        token = self._start_session(user)
        self.bus.publish(EventEnvelope.make(
            EventType.TENANT_PROVISIONED, source=self.source,
            tenant_id=tenant_id,
            data={"tenant_id": tenant_id, "plan_id": tenant["plan_id"],
                  "admin_email": user["email"]}))
        return {"tenant": tenant, "user": user, "token": token}

    def login(self, data: dict) -> dict:
        tenant_id = _s(data.get("tenant_id"))
        email = _email(data.get("email"))
        password = _s(data.get("password"))
        if tenant_id:
            row = self.repo.get_by_email_raw(tenant_id, email)
        else:
            # normal sign-in: users don't know tenant ids — find the account
            # by email across ALL scopes (platform owner included; password
            # disambiguates — a same-email/same-password collision across
            # tenants is not supported)
            row = next(
                (r for r in self.repo.find_by_email_raw(email)
                 if security.verify_password(password, r["pw_salt"],
                                             r["pw_hash"])), None)
        if not row or not security.verify_password(
                password, row["pw_salt"], row["pw_hash"]):
            raise ProblemError(401, "invalid credentials",
                               rule="auth_failed")
        if row.get("mfa_enabled"):
            if not security.verify_totp(row.get("mfa_secret"),
                                        data.get("mfa_code")):
                raise ProblemError(401, "an MFA code is required",
                                   rule="mfa_required")
        else:
            # WORKSPACE-MANDATED MFA (WS4.1): if this member's workspace requires
            # MFA and they have none enrolled, password alone must NOT mint a
            # session. Enforced SERVER-SIDE here — the ONLY session-minting path —
            # off the DB tenant record, so no client flag can bypass it. We hand
            # back a short-lived setup token so they can enrol and continue.
            user = self.repo._public(row)
            if self._workspace_requires_mfa(user["tenant_id"]):
                # scope the token to MFA setup ONLY — resolve() rejects it for
                # every endpoint except the enrolment path, so a password-only
                # member never gets a working session under the mandate.
                setup = self._start_session(user, ttl=MFA_SETUP_TTL,
                                            scope="mfa_setup")
                raise ProblemError(
                    403, "your workspace requires multi-factor authentication "
                    "— set it up to continue signing in",
                    rule="workspace_mfa_required", setup_token=setup)
        user = self.repo._public(row)
        return {"user": user, "token": self._start_session(user)}

    def _workspace_requires_mfa(self, tenant_id: str) -> bool:
        if not tenant_id:  # platform owner — no workspace mandate applies
            return False
        tenant = self.repo.get_tenant(tenant_id)
        return bool(tenant and tenant.get("require_mfa"))

    # -- MFA (SAAS-NFR-003) -------------------------------------------------
    def _require_mfa_setup_principal(self, token: str) -> dict:
        # enrolment must work for a member BLOCKED by the mandate, so it accepts
        # a scope="mfa_setup" token and skips the mandate check (that is the
        # whole point of the setup token). A full token still works too.
        principal = self.resolve(token, for_mfa_setup=True)
        if not principal:
            raise ProblemError(401, "no active session", rule="no_session")
        return principal

    def enroll_mfa(self, token: str) -> dict:
        principal = self._require_mfa_setup_principal(token)
        secret = security.new_totp_secret()
        self.repo.set_mfa(principal["user_id"], secret, False)
        return {"secret": secret, "enabled": False,
                "provisioning_uri": security.provisioning_uri(
                    secret, principal["email"])}

    def verify_mfa(self, token: str, code: str) -> dict:
        principal = self._require_mfa_setup_principal(token)
        user = self.repo.get_user_raw(principal["user_id"]) or {}
        secret = user.get("mfa_secret")
        if not secret:
            raise ProblemError(422, "MFA is not enrolled", rule="mfa_not_enrolled")
        if not security.verify_totp(secret, code):
            raise ProblemError(401, "invalid MFA code", rule="mfa_invalid")
        self.repo.set_mfa(principal["user_id"], secret, True)
        return {"enabled": True}

    def mfa_status(self, token: str) -> dict:
        principal = self.me(token)
        user = self.repo.get_user_raw(principal["user_id"]) or {}
        return {"enabled": bool(user.get("mfa_enabled"))}

    def _start_session(self, user: dict, *, ttl: timedelta = SESSION_TTL,
                       scope: str = "full") -> str:
        token = security.new_session_token()
        expires = (datetime.now(timezone.utc) + ttl).isoformat()
        self.repo.create_session(token, user, expires, scope=scope)
        return token

    # -- workspace security policy (WS4.1) ----------------------------------
    def _require_tenant_admin(self, token: str) -> dict:
        principal = self.resolve(token)
        if not principal:
            raise ProblemError(401, "no active session", rule="no_session")
        if principal["role"] not in (rbac.OWNER_ROLE, rbac.TENANT_ADMIN_ROLE):
            raise ProblemError(403, "only a workspace admin can change this",
                               rule="forbidden")
        return principal

    def tenant_security(self, token: str) -> dict:
        principal = self.me(token)
        tenant = (self.repo.get_tenant(principal["tenant_id"])
                  if principal["tenant_id"] else None) or {}
        return {"tenant_id": principal["tenant_id"],
                "require_mfa": bool(tenant.get("require_mfa")),
                "can_manage": principal["role"] in (rbac.OWNER_ROLE,
                                                    rbac.TENANT_ADMIN_ROLE)}

    def set_require_mfa(self, token: str, data: dict) -> dict:
        principal = self._require_tenant_admin(token)
        tenant_id = principal["tenant_id"]
        if not tenant_id:
            raise ProblemError(422, "the platform owner has no workspace to "
                               "configure", rule="no_tenant")
        want = bool(data.get("require_mfa"))
        tenant = self.repo.set_require_mfa(tenant_id, want) or {}
        if want:
            # defense in depth: kill live sessions of members without verified
            # MFA now, so the mandate bites immediately (resolve() also enforces
            # it on every subsequent request as the durable backstop).
            self.repo.delete_sessions_for_tenant_without_mfa(tenant_id)
        return {"tenant_id": tenant_id,
                "require_mfa": bool(tenant.get("require_mfa"))}

    # -- role permission matrix (WS4.2) -------------------------------------
    def role_matrix(self, token: str) -> dict:
        self.me(token)  # any authenticated principal may read it
        return {"roles": rbac.role_matrix()}

    def resolve(self, token: str, *, for_mfa_setup: bool = False) -> dict | None:
        row = self.repo.get_session(_s(token))
        if not row:
            return None
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            return None
        if expires < datetime.now(timezone.utc):
            self.repo.delete_session(token)
            return None
        scope = row.get("scope") or "full"
        # (i) an mfa_setup-scoped token is accepted ONLY on the enrolment path.
        # Everywhere else it must not authenticate — otherwise it is a full
        # session in disguise (the CRITICAL hole).
        if scope == "mfa_setup" and not for_mfa_setup:
            raise ProblemError(403, "this token is only valid for MFA setup",
                               rule="mfa_setup_scope")
        principal = {"user_id": row["user_id"], "tenant_id": row["tenant_id"],
                     "role": row["role"], "email": row["email"]}
        # (ii) enforce the workspace mandate on the SESSION-VALIDATION path so it
        # also locks out sessions minted BEFORE the mandate was turned on. The
        # enrolment path (for_mfa_setup) skips this so a blocked member can enrol.
        if not for_mfa_setup and self._session_blocked_by_mandate(principal):
            raise ProblemError(
                403, "your workspace requires multi-factor authentication "
                "— set it up to continue signing in",
                rule="workspace_mfa_required")
        return principal

    def _session_blocked_by_mandate(self, principal: dict) -> bool:
        """True when the principal's workspace requires MFA and the user has no
        verified MFA — the check that revokes pre-existing non-MFA sessions."""
        if not self._workspace_requires_mfa(principal.get("tenant_id")):
            return False
        user = self.repo.get_user_raw(principal["user_id"]) or {}
        return not bool(user.get("mfa_enabled"))

    def me(self, token: str) -> dict:
        principal = self.resolve(token)
        if not principal:
            raise ProblemError(401, "no active session", rule="no_session")
        # workspace identity is SERVER-side: the header chip renders what the
        # account record says, not whatever the browser cached at signup
        user = self.repo.get_user_raw(principal["user_id"]) or {}
        tenant = (self.repo.get_tenant(principal["tenant_id"])
                  if principal["tenant_id"] else None)
        return {**principal,
                "name": user.get("name") or "",
                "tenant_name": (tenant or {}).get("name")
                or ("Platform" if principal["tenant_id"] == PLATFORM_TENANT
                    else "")}

    def logout(self, token: str) -> dict:
        self.repo.delete_session(_s(token))
        return {"ok": True}

    # -- password reset -------------------------------------------------------
    # No SMTP in this deployment: the code is returned in the response, and the
    # UI labels it as delivered on-screen in this environment (would be email
    # in production). Codes are one-time, hashed at rest, 15-minute expiry.
    def request_reset(self, data: dict) -> dict:
        email = _email(data.get("email"))
        generic = {"ok": True,
                   "message": "If that account exists, a reset code has been "
                              "issued. Codes expire in 15 minutes."}
        if not email or not self.repo.find_by_email_raw(email):
            return generic  # never reveal whether an account exists
        code = security.new_reset_code()
        salt, code_hash = security.hash_password(code)
        expires = (datetime.now(timezone.utc) + RESET_CODE_TTL).isoformat()
        self.repo.save_reset_code(email, salt, code_hash, expires)
        return {**generic, "delivery": "on-screen (no email in this "
                "environment)", "reset_code": code}

    def complete_reset(self, data: dict) -> dict:
        email = _email(data.get("email"))
        code = _s(data.get("code"))
        bad = ProblemError(422, "invalid or expired reset code",
                           rule="reset_code_invalid")
        row = self.repo.get_reset_code(email)
        if not row or not code:
            raise bad
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            self.repo.delete_reset_code(email)
            raise bad
        if not security.verify_password(code, row["code_salt"], row["code_hash"]):
            raise bad
        _check_password_policy(_s(data.get("new_password")))
        users = self.repo.find_by_email_raw(email)
        salt, pw_hash = security.hash_password(_s(data.get("new_password")))
        for u in users:  # same email across workspaces = same person
            self.repo.update_password(u["id"], salt, pw_hash)
            self.repo.delete_sessions_for_user(u["id"])
        self.repo.delete_reset_code(email)  # one-time use
        return {"ok": True, "accounts_updated": len(users)}

    # -- owner control plane ------------------------------------------------
    def _require_owner(self, token: str) -> dict:
        principal = self.resolve(token)
        if not principal or principal["role"] != rbac.OWNER_ROLE:
            raise ProblemError(403, "owner control plane is restricted",
                               rule="forbidden")
        return principal

    def provision_tenant(self, token: str, data: dict) -> dict:
        self._require_owner(token)
        tenant_id = new_id()
        plan_id = _s(data.get("plan_id")) or entitlements.DEFAULT_PLAN_ID
        if not self.repo.get_plan(plan_id):
            raise ProblemError(422, f"unknown plan: {plan_id}",
                               rule="plan_unknown")
        tenant = self.repo.create_tenant(
            tenant_id, _s(data.get("name")) or "Tenant", plan_id, TENANT_ACTIVE)
        admin = self._add_user(tenant_id, data.get("admin_email"),
                               data.get("admin_password"),
                               rbac.TENANT_ADMIN_ROLE, "Tenant Admin")
        self.bus.publish(EventEnvelope.make(
            EventType.TENANT_PROVISIONED, source=self.source,
            tenant_id=tenant_id,
            data={"tenant_id": tenant_id, "plan_id": plan_id}))
        return {"tenant": tenant, "admin": admin}

    def list_tenants(self, token: str) -> dict:
        self._require_owner(token)
        return {"tenants": self.repo.list_tenants()}

    def create_plan(self, token: str, data: dict) -> dict:
        self._require_owner(token)
        name = _s(data.get("name"))
        if not name:
            raise ProblemError(422, "plan name is required", rule="name_required")
        plan_id = entitlements.plan_id_from_name(name)
        if self.repo.get_plan(plan_id):
            raise ProblemError(409, f"plan already exists: {name}",
                               rule="plan_exists")
        return self.repo.create_plan(
            plan_id, name, entitlements.normalize_features(data.get("features")))

    def list_plans(self, token: str) -> dict:
        self._require_owner(token)
        return {"plans": self.repo.list_plans()}

    def assign_plan(self, token: str, data: dict) -> dict:
        self._require_owner(token)
        tenant_id = _s(data.get("tenant_id"))
        plan_id = _s(data.get("plan_id"))
        if not self.repo.get_tenant(tenant_id):
            raise ProblemError(404, "unknown tenant", rule="tenant_unknown")
        if not self.repo.get_plan(plan_id):
            raise ProblemError(422, "unknown plan", rule="plan_unknown")
        return self.repo.set_tenant_plan(tenant_id, plan_id)

    def set_override(self, token: str, data: dict) -> dict:
        self._require_owner(token)
        feature = _s(data.get("feature"))
        if feature not in entitlements.FEATURES:
            raise ProblemError(422, f"unknown feature: {feature}",
                               rule="feature_unknown")
        self.repo.set_override(_s(data.get("tenant_id")), feature,
                               bool(data.get("enabled")))
        return self.entitlements(_s(data.get("tenant_id")))

    # -- subscription billing (SAAS-REQ-002) -------------------------------
    def set_billing(self, token: str, data: dict) -> dict:
        self._require_owner(token)
        tenant_id = _s(data.get("tenant_id"))
        status = _s(data.get("billing_status"))
        if status not in billing.BILLING_STATUSES:
            raise ProblemError(422, "unknown billing status",
                               rule="billing_status_invalid")
        if not self.repo.get_tenant(tenant_id):
            raise ProblemError(404, "unknown tenant", rule="tenant_unknown")
        return self.repo.set_billing(tenant_id, status,
                                     _s(data.get("grace_until")) or None)

    def billing_access(self, tenant_id: str) -> dict:
        tenant = self.repo.get_tenant(_s(tenant_id))
        if not tenant:
            raise ProblemError(404, "unknown tenant", rule="tenant_unknown")
        access = billing.effective_access(
            tenant.get("billing_status"), tenant.get("grace_until"))
        return {"tenant_id": tenant_id, **access}

    # -- entitlements + authorize ------------------------------------------
    def entitlements(self, tenant_id: str) -> dict:
        tenant = self.repo.get_tenant(_s(tenant_id))
        if not tenant:
            raise ProblemError(404, "unknown tenant", rule="tenant_unknown")
        plan = self.repo.get_plan(tenant["plan_id"]) or \
            self.repo.get_plan(entitlements.DEFAULT_PLAN_ID)
        overrides = self.repo.list_overrides(tenant_id)
        eff = entitlements.effective(plan["features"] if plan else [], overrides)
        return {"tenant_id": tenant_id, "plan_id": tenant["plan_id"],
                "effective": eff,
                "features": [f for f, v in eff.items() if v["enabled"]]}

    def authorize(self, data: dict) -> dict:
        return rbac.authorize(data.get("principal") or {},
                              _s(data.get("capability")),
                              data.get("resource") or {})
