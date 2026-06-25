"""
ANDS Submission Portal — fees & fee-mitigation domain logic.

Pure, dependency-free (Python 3 standard library only) implementation of the
Health-Canada drug-submission fee model:

* REQ-035 — resolve an ANDS to its Schedule 1 fee grouping ('Comparative
  studies'), compute the current fiscal-year amount through a per-grouping
  escalation table keyed by the April-1 effective date, applying a CPI
  escalation (Fee = A + (A x B)) to most groupings but a fixed 2% ministerial
  escalation to the subset that uses it (DMF, Certificate of Pharmaceutical
  Product, Certificate of Supplemental Protection, Human Drug Dealer's Licence).
  The ANDS comparative-studies seeds are $70,750 (FY2025-26) and $71,953
  (FY2026-27); $53,836 is a historical CPI-anchor seed only, never shown current.
* REQ-036 — fee mitigation: 100% small-business first-submission remission, 50%
  subsequent-ANDS remission (gated on an affiliation/financial attestation
  upload), and deferral-until-NOC, with invoice status per sponsor/submission.
* REQ-037 — the per-DIN annual Right-to-Sell fee, separate from one-time
  submission fees, keyed by drug type, with the statutory October-1 due date and
  outstanding-balance flags.

Everything here is deterministic and unit-testable; the HTTP/API/UI layer in
server.py is a thin shell over these functions.

Requirement traceability tags (REQ-xxx) reference
specs/ands-submission-portal/requirements.md.
"""

from __future__ import annotations

from datetime import date, datetime


# ---------------------------------------------------------------------------
# Fiscal-year arithmetic (HC fee years run April 1 -> March 31)  — REQ-035
# ---------------------------------------------------------------------------

FISCAL_YEAR_START_MONTH = 4  # April 1


def _as_date(value) -> date:
    """Parse an ISO date/datetime string (or date/datetime) into a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("a submission date is required")
    # Accept a bare date or a full ISO timestamp.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(text[:10])


def fiscal_year(value) -> str:
    """The HC fiscal year label (e.g. '2025-26') containing ``value``.

    April 1 2025 .. March 31 2026 -> '2025-26'.
    """
    d = _as_date(value)
    start = d.year if d.month >= FISCAL_YEAR_START_MONTH else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def fiscal_year_effective_date(fy: str) -> str:
    """The April-1 effective date (ISO) for a fiscal-year label."""
    start = int(str(fy).split("-")[0])
    return f"{start}-04-01"


# ---------------------------------------------------------------------------
# Escalation bases  — REQ-035
# ---------------------------------------------------------------------------

BASIS_CPI = "cpi"                 # Fee = A + (A x B)
BASIS_MINISTERIAL_2PCT = "ministerial-2pct"  # fixed 2% ministerial authority

# The Schedule-1 subset whose annual escalation is the fixed 2% ministerial
# rate rather than CPI (REQ-035).
MINISTERIAL_2PCT_GROUPINGS = frozenset({
    "drug-master-file",
    "certificate-of-pharmaceutical-product",
    "certificate-of-supplemental-protection",
    "human-drug-dealers-licence",
})

# A historical CPI-anchor seed ONLY. Never display this as a current fee.
COMPARATIVE_STUDIES_ANCHOR_SEED = 53836.0  # FY2020-21 base


# ---------------------------------------------------------------------------
# Per-grouping fee table, keyed by fiscal year (updatable as data — REQ-040)
# ---------------------------------------------------------------------------

FEE_GROUPINGS = {
    "comparative-studies": {
        "label": "Comparative studies",
        "basis": BASIS_CPI,
        "rationale": (
            "An ANDS relying on bioequivalence/comparative studies is examined "
            "under the Schedule 1 'Comparative studies' grouping."
        ),
        "amounts": {
            "2025-26": 70750.0,
            "2026-27": 71953.0,
        },
    },
    "drug-master-file": {
        "label": "Drug Master File",
        "basis": BASIS_MINISTERIAL_2PCT,
        "rationale": "DMF fees escalate at the fixed 2% ministerial rate.",
        "amounts": {
            "2025-26": 2231.0,
            "2026-27": 2276.0,
        },
    },
}

# The ANDS submission type always resolves to the comparative-studies grouping.
ANDS_FEE_GROUPING = "comparative-studies"


def escalate(amount: float, basis: str, cpi_rate: float = 0.0) -> float:
    """Apply one year of escalation to ``amount`` under the given basis.

    CPI groupings use Fee = A + (A x B) where B is the CPI rate; the ministerial
    subset uses a fixed 2% regardless of CPI (REQ-035). Result rounded to cents.
    """
    if basis == BASIS_MINISTERIAL_2PCT:
        return round(amount * 1.02, 2)
    if basis == BASIS_CPI:
        return round(amount + (amount * float(cpi_rate or 0.0)), 2)
    raise ValueError(f"unknown escalation basis: {basis!r}")


def resolve_fee(grouping_key: str, submission_date) -> dict:
    """Resolve a Schedule-1 fee grouping to its amount for the fiscal year of
    ``submission_date`` (REQ-035)."""
    grouping = FEE_GROUPINGS.get(grouping_key)
    if grouping is None:
        raise ValueError(f"unknown fee grouping: {grouping_key!r}")
    fy = fiscal_year(submission_date)
    amounts = grouping["amounts"]
    if fy not in amounts:
        # Fall back to the most recent published year on/before this FY, never
        # the historical anchor seed.
        published = sorted(amounts)
        eligible = [y for y in published if y <= fy]
        used_fy = eligible[-1] if eligible else published[0]
    else:
        used_fy = fy
    amount = amounts[used_fy]
    return {
        "grouping": grouping_key,
        "label": grouping["label"],
        "basis": grouping["basis"],
        "rationale": grouping["rationale"],
        "fiscal_year": fy,
        "amount_fiscal_year": used_fy,
        "amount": amount,
        "effective_date": fiscal_year_effective_date(used_fy),
        "currency": "CAD",
    }


def resolve_ands_fee(submission_date) -> dict:
    """REQ-035: resolve an ANDS to its 'Comparative studies' fee for the
    fiscal year of the submission date. Never returns the $53,836 anchor seed."""
    result = resolve_fee(ANDS_FEE_GROUPING, submission_date)
    result["anchor_seed_excluded"] = COMPARATIVE_STUDIES_ANCHOR_SEED
    assert result["amount"] != COMPARATIVE_STUDIES_ANCHOR_SEED
    return result


# ---------------------------------------------------------------------------
# Fee mitigation / remission / deferral  — REQ-036
# ---------------------------------------------------------------------------

REMISSION_FIRST_SUBMISSION = 1.0   # 100% small-business first submission
REMISSION_SUBSEQUENT_ANDS = 0.5    # 50% subsequent ANDS (attestation gated)

INVOICE_PENDING = "pending"
INVOICE_DEFERRED = "deferred-until-noc"
INVOICE_REMITTED = "remitted"


def evaluate_fee_mitigation(data: dict) -> dict:
    """REQ-036: evaluate small-business remission / deferral for a fee.

    ``data`` keys: ``fee`` (gross), ``small_business`` (bool), ``first_submission``
    (bool — first-ever drug submission by this sponsor), ``attestation_uploaded``
    (bool), ``defer_until_noc`` (bool).

    Returns the remission rate, net fee, whether an attestation upload is still
    required (which blocks the 50% claim), the invoice status, and a list of
    human-readable notes.
    """
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
        # Subsequent ANDS: 50% remission, gated on the attestation upload.
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

    return {
        "fee": round(fee, 2),
        "remission_rate": remission_rate,
        "net_fee": net_fee,
        "requires_attestation": requires_attestation,
        "deferred": invoice_status == INVOICE_DEFERRED,
        "invoice_status": invoice_status,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Per-DIN annual Right-to-Sell fee  — REQ-037
# ---------------------------------------------------------------------------

DRUG_TYPES = {
    "prescription": "Prescription drug",
    "non-prescription": "Non-prescription drug",
    "disinfectant": "Disinfectant",
    "biocide": "Biocide",
}

# Annual Right-to-Sell fee by drug type, keyed by fiscal year (REQ-037).
RIGHT_TO_SELL_FEES = {
    "prescription": {"2025-26": 5531.0, "2026-27": 5626.0},
    "non-prescription": {"2025-26": 3334.0, "2026-27": 3391.0},
    "disinfectant": {"2025-26": 1730.0, "2026-27": 1760.0},
    "biocide": {"2025-26": 1535.0, "2026-27": 1535.0},  # base
}

RIGHT_TO_SELL_DUE_MONTH = 10  # October
RIGHT_TO_SELL_DUE_DAY = 1     # statutory October 1


def right_to_sell_due_date(value) -> str:
    """The statutory October-1 due date in the fiscal year of ``value``."""
    fy = fiscal_year(value)
    start = int(fy.split("-")[0])
    return f"{start}-{RIGHT_TO_SELL_DUE_MONTH:02d}-{RIGHT_TO_SELL_DUE_DAY:02d}"


def resolve_right_to_sell(drug_type: str, as_of) -> dict:
    """REQ-037: resolve the per-DIN annual Right-to-Sell fee for a drug type
    and the October-1 statutory due date of the current fiscal year."""
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
    return {
        "drug_type": key,
        "label": DRUG_TYPES[key],
        "fiscal_year": fy,
        "amount_fiscal_year": used_fy,
        "amount": amounts[used_fy],
        "due_date": right_to_sell_due_date(as_of),
        "currency": "CAD",
    }


def right_to_sell_status(drug_type: str, as_of, paid: bool = False) -> dict:
    """REQ-037: per-DIN Right-to-Sell record with an outstanding-balance flag
    and an approaching-due reminder when within 60 days of October 1."""
    rec = resolve_right_to_sell(drug_type, as_of)
    due = _as_date(rec["due_date"])
    today = _as_date(as_of)
    days_to_due = (due - today).days
    outstanding = not paid
    rec.update({
        "paid": bool(paid),
        "outstanding_balance": outstanding,
        "days_to_due": days_to_due,
        "reminder_due": outstanding and 0 <= days_to_due <= 60,
        "overdue": outstanding and days_to_due < 0,
    })
    return rec
