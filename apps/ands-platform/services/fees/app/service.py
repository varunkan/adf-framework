"""Fees application service — thin wrapper translating domain errors to HTTP."""

from __future__ import annotations

from ands_shared import ProblemError

from . import fees


class FeesService:
    def ands_fee(self, submission_date: str) -> dict:
        try:
            return fees.resolve_ands_fee(submission_date)
        except ValueError as exc:
            raise ProblemError(422, str(exc), rule="invalid_input")

    def fee(self, grouping: str, submission_date: str) -> dict:
        try:
            return fees.resolve_fee(grouping, submission_date)
        except ValueError as exc:
            raise ProblemError(422, str(exc), rule="invalid_input")

    def mitigation(self, data: dict) -> dict:
        return fees.evaluate_fee_mitigation(data)

    def right_to_sell(self, drug_type: str, as_of: str, paid: bool) -> dict:
        try:
            return fees.right_to_sell_status(drug_type, as_of, paid)
        except ValueError as exc:
            raise ProblemError(422, str(exc), rule="invalid_input")

    def groupings(self) -> dict:
        return {"groupings": [
            {"key": k, "label": v["label"], "basis": v["basis"],
             "fiscal_years": sorted(v["amounts"])}
            for k, v in fees.FEE_GROUPINGS.items()],
            "drug_types": fees.DRUG_TYPES}
