"""ANDS content model — module-level applicability gating (ported, pure).

The authoritative "which modules an ANDS needs" logic the section tree binds to
(ported from the monolith ``content_model``). An ANDS relying on comparative
bioequivalence (the CS-BE path) suppresses the nonclinical/clinical summaries
(2.4–2.7) and never needs Module 4; Module 2.3 (QOS) and Modules 1/3/5 stay
required. Nothing here re-encodes the section tree — it only says, per module,
required vs suppressed vs not-applicable.
"""

from __future__ import annotations

# Submission types we route (mirrors journey.drug_intake / monolith).
SUBMISSION_TYPES = ("NDS", "ANDS", "SNDS", "SANDS", "DIN")

# 2.4–2.7 are suppressed on the comparative-BE (CS-BE) ANDS path.
CS_BE_SUPPRESSED = ("2.4", "2.5", "2.6", "2.7")

_ANDS_MODULES = (
    {"module": "1", "title": "Administrative & regional (Canada)", "required": True,
     "cs_be_suppressed": False},
    {"module": "2.3", "title": "Quality Overall Summary (QOS-CE)", "required": True,
     "cs_be_suppressed": False},
    {"module": "2.4", "title": "Nonclinical Overview", "required": False,
     "cs_be_suppressed": True},
    {"module": "2.5", "title": "Clinical Overview", "required": False,
     "cs_be_suppressed": True},
    {"module": "2.6", "title": "Nonclinical Written & Tabulated Summaries",
     "required": False, "cs_be_suppressed": True},
    {"module": "2.7", "title": "Clinical Summary", "required": False,
     "cs_be_suppressed": True},
    {"module": "3", "title": "Quality (CMC)", "required": True,
     "cs_be_suppressed": False},
    {"module": "4", "title": "Nonclinical Study Reports", "required": False,
     "cs_be_suppressed": False},
    {"module": "5", "title": "Clinical Study Reports (BE reports)", "required": True,
     "cs_be_suppressed": False},
)


def ands_content_model(cs_be_only: bool = True) -> dict:
    """Per-module gating for an ANDS. ``cs_be_only`` (the default generic path)
    suppresses 2.4–2.7. Module 4 is never required for a generic ANDS."""
    cs_be_only = bool(cs_be_only)
    modules = []
    for spec in _ANDS_MODULES:
        suppressed = cs_be_only and spec["cs_be_suppressed"]
        required = False if (suppressed or spec["cs_be_suppressed"]) \
            else spec["required"]
        modules.append({"module": spec["module"], "title": spec["title"],
                        "required": required, "suppressed": suppressed,
                        "applicable": not suppressed})
    return {"submission_type": "ANDS", "cs_be_only": cs_be_only,
            "module4_required": False, "modules": modules}


def module_gate(module: str, cs_be_only: bool = True) -> dict:
    """The gating for the top-level module a section belongs to (e.g. '3.2.S' →
    '3'; '2.3' → '2.3'). Returns {required, suppressed, applicable}."""
    module = str(module or "").strip()
    model = {m["module"]: m for m in ands_content_model(cs_be_only)["modules"]}
    # exact match (e.g. '2.3'), else top-level digit (e.g. '3' for '3.2.P')
    if module in model:
        m = model[module]
    else:
        top = module.split(".")[0]
        if top == "4":
            return {"required": False, "suppressed": False, "applicable": False,
                    "na": True}
        m = model.get(top, {"required": False, "suppressed": False,
                            "applicable": True})
    na = module.split(".")[0] == "4"
    out = {"required": False if na else bool(m.get("required")),
           "suppressed": bool(m.get("suppressed")),
           "applicable": False if na else bool(m.get("applicable", True)),
           "na": na}
    return out
