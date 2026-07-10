from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .. import domain_path  # noqa: F401
import auth
from ..deps import get_control_plane
from ..storage.control_plane import ControlPlaneStore, DuplicateTenant, STATUS_SUSPENDED

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    company: str = Field(min_length=1)
    email: str
    password: str = Field(min_length=1)
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)
    tenant_id: str = ""


def _bearer(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        return ""
    return authorization[7:].strip()


@router.post("/signup", status_code=201)
def signup(
    payload: SignupRequest,
    cp: ControlPlaneStore = Depends(get_control_plane),
) -> dict:
    try:
        tenant = cp.create_tenant(payload.company, payload.email, actor="self-serve")
    except DuplicateTenant as dup:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "tenant_exists",
                "detail": (
                    "a company is already registered with this email; "
                    "please sign in instead"
                ),
                "tenant_id": dup.existing["id"],
            },
        ) from dup
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    try:
        user = cp.create_user(
            tenant["id"],
            payload.email,
            payload.password,
            role=auth.TENANT_ADMIN_ROLE,
            name=payload.name,
        )
    except ValueError as exc:
        cp.delete_tenant(tenant["id"], "self-serve", archive=False)
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    token = cp.start_session(user)
    return {"tenant": tenant, "user": user, "token": token}


@router.post("/login")
def login(
    payload: LoginRequest,
    cp: ControlPlaneStore = Depends(get_control_plane),
) -> dict:
    email = payload.email.strip().lower()
    user = None
    tenant_id = payload.tenant_id.strip()
    if tenant_id:
        user = cp.authenticate(tenant_id, email, payload.password)
    else:
        for tenant in cp.list_tenants(include_deleted=True):
            candidate = cp.authenticate(tenant["id"], email, payload.password)
            if candidate is not None:
                user = candidate
                tenant_id = tenant["id"]
                break
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "invalid credentials"})
    tenant = cp.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail={"error": "invalid credentials"})
    if tenant["status"] == STATUS_SUSPENDED:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "suspended",
                "detail": (
                    "This workspace is suspended. Contact the platform owner."
                ),
            },
        )
    token = cp.start_session(user)
    return {
        "token": token,
        "role": user["role"],
        "tenant_id": tenant_id,
        "redirect": "/",
    }


@router.post("/logout")
def logout(
    authorization: Annotated[str | None, Header()] = None,
    cp: ControlPlaneStore = Depends(get_control_plane),
) -> dict:
    token = _bearer(authorization)
    if token:
        cp.end_session(token)
    return {"ok": True}
