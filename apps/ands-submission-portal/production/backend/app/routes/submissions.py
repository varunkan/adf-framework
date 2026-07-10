from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import domain_path  # noqa: F401 — portal modules on sys.path
import domain
from ..deps import get_store
from ..storage.postgres import PostgresStore

router = APIRouter(prefix="/api", tags=["submissions"])


class IntakePayload(BaseModel):
    applicant: str = Field(min_length=1)
    drug_product: str = Field(min_length=1)
    dossier_id: str = Field(min_length=1)
    sequence: str = Field(min_length=4, max_length=4)
    contact_email: str


class PackageJobRequest(BaseModel):
    dossier_id: str
    sequence: str


def _intake_dict(payload: IntakePayload) -> dict:
    """Merge client fields with fixed ANDS type (matches monolith server.py)."""
    data = payload.model_dump()
    data["submission_type"] = domain.MVP_SUBMISSION_TYPE
    return data


@router.post("/validate")
def validate_intake(
    payload: IntakePayload,
    store: PostgresStore = Depends(get_store),
) -> dict[str, Any]:
    data = _intake_dict(payload)
    prior = store.prior_sequences(data["dossier_id"])
    errors = domain.validate_intake(data, prior_sequences=prior)
    return {"valid": not errors, "errors": errors}


@router.get("/submissions")
def list_submissions(store: PostgresStore = Depends(get_store)) -> dict:
    return {"submissions": store.list_submissions()}


@router.get("/submissions/{submission_id}")
def get_submission(
    submission_id: int,
    store: PostgresStore = Depends(get_store),
) -> dict:
    record = store.get_submission(submission_id)
    if not record:
        raise HTTPException(status_code=404, detail="Submission not found")
    return record


@router.post("/submissions", status_code=201)
def create_submission(
    payload: IntakePayload,
    store: PostgresStore = Depends(get_store),
) -> dict:
    data = _intake_dict(payload)
    prior = store.prior_sequences(data["dossier_id"])
    errors = domain.validate_intake(data, prior_sequences=prior)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    record = store.add_submission(data, domain.MVP_SUBMISSION_TYPE)
    return record


@router.post("/packages/jobs", status_code=202)
def enqueue_package(
    payload: PackageJobRequest,
    store: PostgresStore = Depends(get_store),
) -> dict:
    job = store.enqueue_package_job(payload.dossier_id, payload.sequence)
    return {"job": job}
