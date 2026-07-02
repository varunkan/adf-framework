"""FastAPI surface for the identity service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header, Query

from ands_shared import ProblemError, create_app

from . import rbac
from .models import (AssignPlanIn, AuthorizeIn, BillingIn, CreatePlanIn,
                     LoginIn, MfaVerifyIn, OverrideIn, ProvisionTenantIn,
                     ResetCompleteIn, ResetRequestIn, SignupIn)
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
