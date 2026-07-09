"""Heuristic detection of a CDSA-scheduled (controlled) substance from a product
name — swarm r7 (e970011).

An opioid / narcotic / stimulant / benzodiazepine etc. is scheduled under the
Controlled Drugs and Substances Act (CDSA), triggering Office of Controlled
Substances (OCS) obligations BEYOND the drug submission. The tool defaulted
controlled_substance=false with no inference, so an opioid dossier silently
omitted the CDSA/OCS advisory. This module surfaces a SUGGESTION (never an
assertion): if the product name matches a known scheduled-substance term, the
builder prompts the filer to confirm. It does not override the user's explicit
controlled_substance flag.

HONEST: keyword matching on the product name is heuristic — it flags for
confirmation, it does not adjudicate the CDSA schedule. Pure, stdlib-only.
"""

from __future__ import annotations

import re

# Representative CDSA-scheduled substances + narcotic/stimulant class terms.
# Not exhaustive (the CDSA schedules are long) — enough to catch the common
# opioids, stimulants, benzodiazepines and cannabis so the advisory is surfaced.
_SCHEDULED_TERMS = (
    # class terms
    "opioid", "narcotic", "controlled substance", "amphetamine",
    "benzodiazepine", "barbiturate", "cannabis", "cannabinoid",
    # common opioids
    "oxycodone", "oxycontin", "hydrocodone", "hydromorphone", "morphine",
    "codeine", "fentanyl", "sufentanil", "buprenorphine", "methadone",
    "tapentadol", "tramadol", "meperidine",
    # stimulants
    "methylphenidate", "dexamphetamine", "dextroamphetamine", "lisdexamfetamine",
    "modafinil",
    # benzodiazepines / sedatives
    "diazepam", "lorazepam", "alprazolam", "clonazepam", "midazolam",
    "zopiclone", "zolpidem",
    # cannabinoids
    "dronabinol", "nabilone", "nabiximols", "tetrahydrocannabinol", "thc",
    # ketamine / other
    "ketamine", "phentermine",
)

_PATTERNS = [(t, re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE))
             for t in _SCHEDULED_TERMS]


def detect(*texts: str) -> str | None:
    """The first scheduled-substance term found across the given text(s), or None.
    Word-boundary matched so 'code' does not match 'codeine' and vice-versa."""
    blob = " ".join(str(t or "") for t in texts)
    if not blob.strip():
        return None
    for term, pat in _PATTERNS:
        if pat.search(blob):
            return term
    return None
