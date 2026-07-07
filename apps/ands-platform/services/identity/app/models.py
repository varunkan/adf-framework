"""Pydantic request models for the identity API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SignupIn(BaseModel):
    email: str = ""
    password: str = ""
    name: str = ""
    company_name: str = ""


class LoginIn(BaseModel):
    email: str = ""
    password: str = ""
    tenant_id: str = ""
    mfa_code: str = ""


class ReauthIn(BaseModel):
    email: str = ""
    password: str = ""
    mfa_code: str = ""


class MfaVerifyIn(BaseModel):
    code: str = ""


class ResetRequestIn(BaseModel):
    email: str = ""


class ResetCompleteIn(BaseModel):
    email: str = ""
    code: str = ""
    new_password: str = ""


class ProvisionTenantIn(BaseModel):
    name: str = ""
    plan_id: str = ""
    admin_email: str = ""
    admin_password: str = ""


class CreatePlanIn(BaseModel):
    name: str = ""
    features: list[str] = Field(default_factory=list)


class AssignPlanIn(BaseModel):
    tenant_id: str = ""
    plan_id: str = ""


class OverrideIn(BaseModel):
    tenant_id: str = ""
    feature: str = ""
    enabled: bool = True


class AuthorizeIn(BaseModel):
    principal: dict = Field(default_factory=dict)
    capability: str = ""
    resource: dict = Field(default_factory=dict)


class BillingIn(BaseModel):
    tenant_id: str = ""
    billing_status: str = ""
    grace_until: str = ""


class RequireMfaIn(BaseModel):
    require_mfa: bool = False


class RequireSodIn(BaseModel):
    require_sod: bool = False


# -- CAMP-SSO-OIDC ----------------------------------------------------------
class SsoConfigIn(BaseModel):
    enabled: bool = False
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""


class SsoAuthorizeIn(BaseModel):
    tenant_id: str = ""
    redirect_uri: str = ""


class SsoCallbackIn(BaseModel):
    state: str = ""
    code: str = ""
