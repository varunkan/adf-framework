"""HC ANDS fee engine — pure, deterministic (Fees Order, CPI-indexed each Apr 1).

A focused, dossier-service view of the Health Canada Fees Order figures that the
mesh ``fees`` service owns. The ANDS review fee is examined under the Schedule 1
"Comparative studies" grouping (an ANDS relies on bioequivalence/comparative
studies); its figures are CPI-indexed each April 1 (start of the federal fiscal
year). Small-business (SME) applicants get a 50% pre-market remission, or a 100%
waiver on their first-ever submission — but SME status MUST be granted before the
submission is filed. The per-DIN Right-to-Sell fee is annual and due October 1.

Figures are reused verbatim from the mesh ``fees`` service (do NOT invent a
number); ``as_of`` is a 'YYYY-MM-DD' string so the module stays wall-clock free.
"""

from __future__ import annotations

from datetime import date, datetime

CURRENCY = "CAD"
FISCAL_YEAR_START_MONTH = 4

# ANDS review fee is examined under the Schedule-1 "Comparative studies"
# grouping (basis: CPI-indexed each April 1). Figures ported verbatim from the
# mesh fees service (services/fees/app/fees.py FEE_GROUPINGS).
ANDS_REVIEW_FEE_BASIS = "comparative-studies (Schedule 1, CPI-indexed Apr 1)"
ANDS_REVIEW_FEES = {"2025-26": 70750.0, "2026-27": 71953.0}

# Small-business (SME) mitigation (mesh: REMISSION_* in evaluate_fee_mitigation).
SME_PREMARKET_REDUCTION = 0.5      # 50% subsequent-ANDS remission
SME_FIRST_EVER_WAIVER = 1.0        # 100% first-ever-submission remission
SME_STATUS_NOTE = ("Small-business status must be granted by Health Canada "
                   "before the submission is filed.")

# Per-DIN Right-to-Sell (annual). ANDS pharmaceuticals -> "prescription" drug
# type; figures ported verbatim from the mesh RIGHT_TO_SELL_FEES table. Due Oct 1.
RIGHT_TO_SELL_FEES = {"2025-26": 5531.0, "2026-27": 5626.0}
RIGHT_TO_SELL_DUE_MONTH = 10
RIGHT_TO_SELL_DUE_DAY = 1


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("an as_of date is required")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(text[:10])


def fiscal_year(as_of) -> str:
    """The federal fiscal year (starting April 1) containing ``as_of``."""
    d = _as_date(as_of)
    start = d.year if d.month >= FISCAL_YEAR_START_MONTH else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _resolve_amount(table: dict, fy: str) -> tuple[str, float]:
    """Fiscal-year-appropriate figure: exact match, else the latest published
    year at or before ``fy`` (figures carry forward until the next Apr-1 index)."""
    if fy in table:
        return fy, table[fy]
    published = sorted(table)
    eligible = [y for y in published if y <= fy]
    used = eligible[-1] if eligible else published[0]
    return used, table[used]


def ands_review_fee(as_of) -> dict:
    """ANDS review fee for the fiscal year that contains ``as_of``."""
    fy = fiscal_year(as_of)
    used_fy, amount = _resolve_amount(ANDS_REVIEW_FEES, fy)
    return {"fiscal_year": fy, "amount": amount, "currency": CURRENCY,
            "basis": ANDS_REVIEW_FEE_BASIS, "amount_fiscal_year": used_fy}


def small_business_mitigation(amount, *, sme_granted: bool,
                              first_ever_submission: bool) -> dict:
    """SME pre-market mitigation on a review-fee ``amount``.

    100% waiver on a first-ever submission, else 50% pre-market reduction; both
    require SME status to be GRANTED before filing. No status -> full fee payable.
    """
    amount = round(float(amount or 0.0), 2)
    if not sme_granted:
        return {"reduction": 0.0, "waived": False, "payable": amount,
                "note": SME_STATUS_NOTE + " Not granted; full fee payable."}
    if first_ever_submission:
        return {"reduction": round(amount * SME_FIRST_EVER_WAIVER, 2),
                "waived": True, "payable": 0.0,
                "note": "100% first-ever-submission waiver applied. "
                        + SME_STATUS_NOTE}
    reduction = round(amount * SME_PREMARKET_REDUCTION, 2)
    return {"reduction": reduction, "waived": False,
            "payable": round(amount - reduction, 2),
            "note": "50% subsequent-ANDS pre-market reduction applied. "
                    + SME_STATUS_NOTE}


def right_to_sell_due_date(as_of) -> str:
    """The statutory October-1 due date within ``as_of``'s fiscal year."""
    start = int(fiscal_year(as_of).split("-")[0])
    return f"{start}-{RIGHT_TO_SELL_DUE_MONTH:02d}-{RIGHT_TO_SELL_DUE_DAY:02d}"


def right_to_sell(as_of, *, sme_granted: bool = False) -> dict:
    """Annual per-DIN Right-to-Sell fee, due October 1 of ``as_of``'s FY.

    SME status carries a 50% reduction on the annual fee; note that status must
    be granted before it applies.
    """
    fy = fiscal_year(as_of)
    used_fy, gross = _resolve_amount(RIGHT_TO_SELL_FEES, fy)
    if sme_granted:
        amount = round(gross * (1.0 - SME_PREMARKET_REDUCTION), 2)
        note = ("Annual Right-to-Sell fee, due Oct 1; 50% small-business "
                "reduction applied. " + SME_STATUS_NOTE)
    else:
        amount = gross
        note = "Annual Right-to-Sell fee, due Oct 1 (full fee)."
    return {"amount": amount, "due_date": right_to_sell_due_date(as_of),
            "note": note, "fiscal_year": fy, "amount_fiscal_year": used_fy,
            "currency": CURRENCY}
