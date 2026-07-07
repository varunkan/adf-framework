"""HC fee domain — pure, deterministic (ported verbatim from the monolith).

REQ-035 fee resolution + fiscal-year escalation, REQ-036 remission/deferral,
REQ-037 per-DIN Right-to-Sell fee with the statutory October-1 due date.
"""

from __future__ import annotations

from datetime import date, datetime

FISCAL_YEAR_START_MONTH = 4


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("a date is required")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(text[:10])


def fiscal_year(value) -> str:
    d = _as_date(value)
    start = d.year if d.month >= FISCAL_YEAR_START_MONTH else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def fiscal_year_effective_date(fy: str) -> str:
    start = int(str(fy).split("-")[0])
    return f"{start}-04-01"


BASIS_CPI = "cpi"
BASIS_MINISTERIAL_2PCT = "ministerial-2pct"
MINISTERIAL_2PCT_GROUPINGS = frozenset({
    "drug-master-file", "certificate-of-pharmaceutical-product",
    "certificate-of-supplemental-protection", "human-drug-dealers-licence"})
COMPARATIVE_STUDIES_ANCHOR_SEED = 53836.0

FEE_GROUPINGS = {
    "comparative-studies": {
        "label": "Comparative studies", "basis": BASIS_CPI,
        "rationale": ("An ANDS relying on bioequivalence/comparative studies is "
                      "examined under the Schedule 1 'Comparative studies' "
                      "grouping."),
        "amounts": {"2025-26": 70750.0, "2026-27": 71953.0}},
    # Amounts per Health Canada, "Fees for Drug Master Files" (page dated
    # 2025-12-01): New Master File Registration $1,407 (as of April 1, 2025)
    # / $1,436 (as of April 1, 2026); Update $611 / $624; Letter of Access
    # $200 / $204.
    # https://www.canada.ca/en/health-canada/services/drugs-health-products/funding-fees/fees-respect-human-drugs-medical-devices/fees-master-files-human-drugs.html
    "drug-master-file": {
        "label": "Drug Master File (new registration)",
        "basis": BASIS_MINISTERIAL_2PCT,
        "rationale": ("New Master File registration fee; DMF fees escalate "
                      "at the fixed 2% ministerial rate. Other DMF fee "
                      "categories: Update $611 (2025-26) / $624 (2026-27); "
                      "Letter of Access $200 / $204. Source: Health Canada, "
                      "'Fees for Drug Master Files'."),
        "amounts": {"2025-26": 1407.0, "2026-27": 1436.0}},
}
ANDS_FEE_GROUPING = "comparative-studies"


def escalate(amount: float, basis: str, cpi_rate: float = 0.0) -> float:
    if basis == BASIS_MINISTERIAL_2PCT:
        return round(amount * 1.02, 2)
    if basis == BASIS_CPI:
        return round(amount + (amount * float(cpi_rate or 0.0)), 2)
    raise ValueError(f"unknown escalation basis: {basis!r}")


def resolve_fee(grouping_key: str, submission_date) -> dict:
    grouping = FEE_GROUPINGS.get(grouping_key)
    if grouping is None:
        raise ValueError(f"unknown fee grouping: {grouping_key!r}")
    fy = fiscal_year(submission_date)
    amounts = grouping["amounts"]
    if fy not in amounts:
        published = sorted(amounts)
        eligible = [y for y in published if y <= fy]
        used_fy = eligible[-1] if eligible else published[0]
    else:
        used_fy = fy
    return {"grouping": grouping_key, "label": grouping["label"],
            "basis": grouping["basis"], "rationale": grouping["rationale"],
            "fiscal_year": fy, "amount_fiscal_year": used_fy,
            "amount": amounts[used_fy],
            "effective_date": fiscal_year_effective_date(used_fy),
            "currency": "CAD"}


def resolve_ands_fee(submission_date) -> dict:
    result = resolve_fee(ANDS_FEE_GROUPING, submission_date)
    result["anchor_seed_excluded"] = COMPARATIVE_STUDIES_ANCHOR_SEED
    assert result["amount"] != COMPARATIVE_STUDIES_ANCHOR_SEED
    return result


REMISSION_FIRST_SUBMISSION = 1.0
REMISSION_SUBSEQUENT_ANDS = 0.5
INVOICE_PENDING = "pending"
INVOICE_DEFERRED = "deferred-until-noc"
INVOICE_REMITTED = "remitted"


def evaluate_fee_mitigation(data: dict) -> dict:
    fee = float(data.get("fee") or 0.0)
    small_business = bool(data.get("small_business"))
    first_submission = bool(data.get("first_submission"))
    attestation = bool(data.get("attestation_uploaded"))
    defer = bool(data.get("defer_until_noc"))
    notes = []
    remission_rate = 0.0
    requires_attestation = False
    if small_business and first_submission:
        remission_rate = REMISSION_FIRST_SUBMISSION
        notes.append("100% small-business first-submission remission applied.")
    elif small_business:
        requires_attestation = not attestation
        if attestation:
            remission_rate = REMISSION_SUBSEQUENT_ANDS
            notes.append("50% subsequent-ANDS remission applied "
                         "(attestation on file).")
        else:
            notes.append("50% subsequent-ANDS remission requires an "
                         "affiliation/financial attestation upload.")
    else:
        notes.append("No small-business mitigation; full fee applies.")
    net_fee = round(fee * (1.0 - remission_rate), 2)
    if remission_rate >= 1.0:
        invoice_status = INVOICE_REMITTED
    elif defer:
        invoice_status = INVOICE_DEFERRED
        notes.append("Payment deferred until NOC is issued.")
    else:
        invoice_status = INVOICE_PENDING
    return {"fee": round(fee, 2), "remission_rate": remission_rate,
            "net_fee": net_fee, "requires_attestation": requires_attestation,
            "deferred": invoice_status == INVOICE_DEFERRED,
            "invoice_status": invoice_status, "notes": notes}


DRUG_TYPES = {"prescription": "Prescription drug",
              "non-prescription": "Non-prescription drug",
              "disinfectant": "Disinfectant", "biocide": "Biocide"}
RIGHT_TO_SELL_FEES = {
    "prescription": {"2025-26": 5531.0, "2026-27": 5626.0},
    "non-prescription": {"2025-26": 3334.0, "2026-27": 3391.0},
    "disinfectant": {"2025-26": 1730.0, "2026-27": 1760.0},
    "biocide": {"2025-26": 1535.0, "2026-27": 1535.0}}
RIGHT_TO_SELL_DUE_MONTH = 10
RIGHT_TO_SELL_DUE_DAY = 1


def right_to_sell_due_date(value) -> str:
    fy = fiscal_year(value)
    start = int(fy.split("-")[0])
    return f"{start}-{RIGHT_TO_SELL_DUE_MONTH:02d}-{RIGHT_TO_SELL_DUE_DAY:02d}"


def resolve_right_to_sell(drug_type: str, as_of) -> dict:
    key = str(drug_type or "").strip().lower()
    if key not in RIGHT_TO_SELL_FEES:
        raise ValueError(f"unknown drug type: {drug_type!r}")
    fy = fiscal_year(as_of)
    amounts = RIGHT_TO_SELL_FEES[key]
    if fy in amounts:
        used_fy = fy
    else:
        published = sorted(amounts)
        eligible = [y for y in published if y <= fy]
        used_fy = eligible[-1] if eligible else published[0]
    return {"drug_type": key, "label": DRUG_TYPES[key], "fiscal_year": fy,
            "amount_fiscal_year": used_fy, "amount": amounts[used_fy],
            "due_date": right_to_sell_due_date(as_of), "currency": "CAD"}


def right_to_sell_status(drug_type: str, as_of, paid: bool = False) -> dict:
    rec = resolve_right_to_sell(drug_type, as_of)
    due = _as_date(rec["due_date"])
    today = _as_date(as_of)
    days_to_due = (due - today).days
    outstanding = not paid
    rec.update({"paid": bool(paid), "outstanding_balance": outstanding,
                "days_to_due": days_to_due,
                "reminder_due": outstanding and 0 <= days_to_due <= 60,
                "overdue": outstanding and days_to_due < 0})
    return rec
