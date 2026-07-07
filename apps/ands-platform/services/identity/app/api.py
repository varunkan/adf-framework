"""FastAPI surface for the identity service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header, Query

from ands_shared import ProblemError, create_app

from . import rbac
from .models import (AssignPlanIn, AuthorizeIn, BillingIn, CreatePlanIn,
                     LoginIn, MfaVerifyIn, OverrideIn, ProvisionTenantIn,
                     ReauthIn,
                     RequireMfaIn, RequireSodIn, ResetCompleteIn,
                     ResetRequestIn, SignupIn, SsoAuthorizeIn, SsoCallbackIn,
                     SsoConfigIn)
from .service import IdentityService


def _bearer(authorization: str) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return authorization or ""


def build_app(service: IdentityService) -> FastAPI:
    app = create_app(title="identity",
                     description="ANDS auth, tenancy, entitlements & RBAC")
    router = APIRouter(prefix="/api/identity", tags=["identity"])

    # -- auth -----------------------------------------------------------
    @router.post("/auth/signup", status_code=201)
    def signup(body: SignupIn):
        return service.signup(body.model_dump())

    @router.post("/auth/login")
    def login(body: LoginIn):
        return service.login(body.model_dump())

    @router.post("/auth/reauth")
    def reauth(body: ReauthIn):
        return service.reauth(body.model_dump())

    @router.post("/auth/logout")
    def logout(authorization: str = Header(default="")):
        return service.logout(_bearer(authorization))

    @router.get("/auth/me")
    def me(authorization: str = Header(default="")):
        return service.me(_bearer(authorization))

    @router.post("/auth/reset/request")
    def reset_request(body: ResetRequestIn):
        return service.request_reset(body.model_dump())

    @router.post("/auth/reset/complete")
    def reset_complete(body: ResetCompleteIn):
        return service.complete_reset(body.model_dump())

    # -- MFA (SAAS-NFR-003) --------------------------------------------
    @router.post("/auth/mfa/enroll")
    def mfa_enroll(authorization: str = Header(default="")):
        return service.enroll_mfa(_bearer(authorization))

    @router.post("/auth/mfa/verify")
    def mfa_verify(body: MfaVerifyIn, authorization: str = Header(default="")):
        return service.verify_mfa(_bearer(authorization), body.code)

    @router.get("/auth/mfa/status")
    def mfa_status(authorization: str = Header(default="")):
        return service.mfa_status(_bearer(authorization))

    # -- CAMP-SSO-OIDC: standards-based SSO login (OIDC + PKCE) ----------
    # Sign-in paths: unauthenticated on purpose (the user has no session yet).
    @router.post("/auth/sso/authorize")
    def sso_authorize(body: SsoAuthorizeIn):
        return service.sso_authorize(body.model_dump())

    @router.post("/auth/sso/callback")
    def sso_callback(body: SsoCallbackIn):
        return service.sso_callback(body.model_dump())

    # Per-workspace SSO configuration (admin-gated inside the service).
    @router.get("/tenant/sso")
    def get_sso(authorization: str = Header(default="")):
        return service.get_sso(_bearer(authorization))

    @router.post("/tenant/sso")
    def set_sso(body: SsoConfigIn, authorization: str = Header(default="")):
        return service.set_sso(_bearer(authorization), body.model_dump())

    # -- workspace security policy + role matrix (WS4) -----------------
    @router.get("/tenant/security")
    def tenant_security(authorization: str = Header(default="")):
        return service.tenant_security(_bearer(authorization))

    @router.post("/tenant/security/require-mfa")
    def set_require_mfa(body: RequireMfaIn,
                        authorization: str = Header(default="")):
        return service.set_require_mfa(_bearer(authorization),
                                       body.model_dump())

    # TIER3-SOD-ENFORCE: the per-workspace 'enforce segregation of duties'
    # policy. An admin flips it; when on, the sign path hard-blocks a
    # signer-is-author e-signature. Enforcement lives server-side on the sign
    # path (dossier record_esign), not just in this UI toggle.
    @router.post("/tenant/security/require-sod")
    def set_require_sod(body: RequireSodIn,
                        authorization: str = Header(default="")):
        return service.set_require_sod(_bearer(authorization),
                                       body.model_dump())

    # Service-to-service policy read: the sign path (dossier) consults a
    # workspace's require_sod for a tenant. Guarded by the internal-token gate
    # in production (X-Internal-Auth); in-process/tests it is reachable directly.
    @router.get("/internal/workspace-policy")
    def workspace_policy(tenant_id: str = Query(default="")):
        return service.workspace_policy(tenant_id)

    @router.get("/rbac/matrix")
    def rbac_matrix(authorization: str = Header(default="")):
        return service.role_matrix(_bearer(authorization))

    # -- entitlements + authorize ---------------------------------------
    @router.get("/entitlements")
    def entitlements(tenant_id: str = Query(...),
                     authorization: str = Header(default="")):
        principal = service.resolve(_bearer(authorization))
        if not principal:
            raise ProblemError(401, "authentication required", rule="no_session")
        if principal["role"] != rbac.OWNER_ROLE \
                and principal["tenant_id"] != tenant_id:
            raise ProblemError(403, "cross-tenant access denied",
                               rule="cross_tenant_denied")
        return service.entitlements(tenant_id)

    @router.post("/authorize")
    def authorize(body: AuthorizeIn):
        return service.authorize(body.model_dump())

    # -- subscription billing (SAAS-REQ-002) ---------------------------
    @router.post("/owner/billing")
    def set_billing(body: BillingIn, authorization: str = Header(default="")):
        return service.set_billing(_bearer(authorization), body.model_dump())

    @router.get("/billing")
    def billing(tenant_id: str = Query(...),
                authorization: str = Header(default="")):
        principal = service.resolve(_bearer(authorization))
        if not principal:
            raise ProblemError(401, "authentication required", rule="no_session")
        if principal["role"] != rbac.OWNER_ROLE \
                and principal["tenant_id"] != tenant_id:
            raise ProblemError(403, "cross-tenant access denied",
                               rule="cross_tenant_denied")
        return service.billing_access(tenant_id)

    # -- owner control plane --------------------------------------------
    @router.post("/owner/tenants", status_code=201)
    def provision_tenant(body: ProvisionTenantIn,
                         authorization: str = Header(default="")):
        return service.provision_tenant(_bearer(authorization),
                                        body.model_dump())

    @router.get("/owner/tenants")
    def list_tenants(authorization: str = Header(default="")):
        return service.list_tenants(_bearer(authorization))

    @router.post("/owner/plans", status_code=201)
    def create_plan(body: CreatePlanIn, authorization: str = Header(default="")):
        return service.create_plan(_bearer(authorization), body.model_dump())

    @router.get("/owner/plans")
    def list_plans(authorization: str = Header(default="")):
        return service.list_plans(_bearer(authorization))

    @router.post("/owner/tenants/assign-plan")
    def assign_plan(body: AssignPlanIn, authorization: str = Header(default="")):
        return service.assign_plan(_bearer(authorization), body.model_dump())

    @router.post("/owner/overrides")
    def set_override(body: OverrideIn, authorization: str = Header(default="")):
        return service.set_override(_bearer(authorization), body.model_dump())

    app.include_router(router)
    return app
