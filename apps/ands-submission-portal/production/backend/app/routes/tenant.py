from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .. import domain_path  # noqa: F401
import readiness
from ..deps import get_control_plane, require_tenant_session
from ..storage.control_plane import ControlPlaneStore

router = APIRouter(prefix="/api/tenant", tags=["tenant"])


class TenantSubmissionPayload(BaseModel):
    drug_product: str = Field(min_length=1)
    dossier_id: str = Field(min_length=1)
    validation: dict[str, Any] | None = None
    content: dict[str, Any] | None = None
    fees: dict[str, Any] | None = None
    esign: dict[str, Any] | None = None
    transmission: dict[str, Any] | None = None
    lifecycle: dict[str, Any] | None = None
    deadline: dict[str, Any] | None = None


@router.get("/dashboard")
def tenant_dashboard(
    session: dict = Depends(require_tenant_session),
    cp: ControlPlaneStore = Depends(get_control_plane),
    today: str = Query(default=""),
) -> dict:
    if not cp.require_feature(session, "dashboard"):
        raise HTTPException(status_code=403, detail={"error": "feature_disabled"})
    anchor = today.strip() or date.today().isoformat()
    subs = cp.list_records(session["tenant_id"], kind="submission")
    return readiness.dashboard(subs, today=anchor)


@router.get("/submissions")
def list_tenant_submissions(
    session: dict = Depends(require_tenant_session),
    cp: ControlPlaneStore = Depends(get_control_plane),
) -> dict:
    if not cp.require_feature(session, "dossiers"):
        raise HTTPException(status_code=403, detail={"error": "feature_disabled"})
    return {"submissions": cp.list_records(session["tenant_id"], kind="submission")}


@router.post("/submissions", status_code=201)
def create_tenant_submission(
    payload: TenantSubmissionPayload,
    session: dict = Depends(require_tenant_session),
    cp: ControlPlaneStore = Depends(get_control_plane),
) -> dict:
    if not cp.require_feature(session, "dossiers"):
        raise HTTPException(status_code=403, detail={"error": "feature_disabled"})
    record = {
        "drug_product": payload.drug_product.strip(),
        "dossier_id": payload.dossier_id.strip(),
        "by": session["email"],
    }
    for signal in (
        "validation",
        "content",
        "fees",
        "esign",
        "transmission",
        "lifecycle",
        "deadline",
    ):
        value = getattr(payload, signal)
        if isinstance(value, dict):
            record[signal] = value
    return cp.add_record(session["tenant_id"], "submission", record)


@router.get("/nav")
def tenant_nav(
    session: dict = Depends(require_tenant_session),
    cp: ControlPlaneStore = Depends(get_control_plane),
) -> dict:
    tenant = cp.get_tenant(session["tenant_id"])
    if tenant is None:
        raise HTTPException(status_code=404, detail={"error": "tenant not found"})
    features = cp.effective_features(tenant["id"], tenant["plan_id"])
    import navigation

    return {"nav": navigation.tenant_nav(features)}
