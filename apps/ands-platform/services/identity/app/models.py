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
