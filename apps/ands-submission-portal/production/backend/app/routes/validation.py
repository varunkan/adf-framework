from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import domain_path  # noqa: F401
import transmission
import validation

router = APIRouter(prefix="/api", tags=["validation", "transmission"])


@router.get("/validation/rulesets")
def list_rulesets() -> dict[str, Any]:
    return {
        "rulesets": validation.list_ruleset_versions(),
        "active": validation.ACTIVE_RULESET_VERSION,
    }


@router.get("/validation/services")
def list_services() -> dict[str, Any]:
    return {
        "services": [
            {"id": key, "label": label}
            for key, label in validation.EXTERNAL_SERVICES.items()
        ]
    }


@router.get("/transmission/account-types")
def account_types() -> dict[str, Any]:
    return {
        "account_types": [
            {"id": k, "label": v}
            for k, v in transmission.ACCOUNT_TYPES.items()
        ],
        "esg_environment": transmission.ESG_ENVIRONMENT,
        "esg_environment_deployed": transmission.ESG_ENVIRONMENT_DEPLOYED,
        "recipient_center": transmission.RECIPIENT_CENTER,
        "gateway_ceiling_gb": transmission.GATEWAY_CEILING_GB,
    }


@router.post("/transmission/configure")
def configure_esg(payload: dict[str, Any]) -> dict[str, Any]:
    errors = transmission.validate_esg_config(payload)
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "config": transmission.build_esg_config(payload)}


@router.post("/transmission/test-round-trip")
def test_round_trip(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("config") or payload
    cfg = transmission.build_esg_config(raw)
    updated = transmission.complete_test_round_trip(cfg, payload.get("acks") or {})
    allowed, reason = transmission.can_transmit_production(updated)
    return {
        "valid": True,
        "production_enabled": allowed,
        "reason": reason,
        "config": updated,
    }


@router.get("/fees/ands")
def ands_fee() -> dict[str, Any]:
    from datetime import date
    import fees
    return fees.resolve_ands_fee(date.today().isoformat())
