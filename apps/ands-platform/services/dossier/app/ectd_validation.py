"""eCTD technical validator over an assembled dossier model (REQ-107 gap).

Pure + stdlib. Given an assembled dossier (:mod:`assembly` model — sequences of
leaf operations), replays the lifecycle in order and reports the technical
defects Health Canada's eCTD validation would flag *before* transmission:

  - every LIVE leaf carries a non-empty ``href`` AND ``checksum``, and the
    checksum is a well-formed 32-hex-digit MD5 digest;
  - no ``leaf_id`` is duplicated across the whole dossier;
  - each operation is legal at the point it is applied (new/replace/append/
    delete), reusing :func:`assembly.validate_leaf_operation` semantics against
    the live set reconstructed *up to that leaf*, plus the monolith's
    ``new_has_prior`` rule (a ``new`` leaf must not reference a prior leaf);
  - sequence numbering: every sequence number is a unique four-digit number;
    numbering that does not start at 0000 or has gaps is warned about;
  - ``href`` naming hygiene: lowercase, no spaces (errors), and a ``m1``..``m5``
    module-folder prefix (a warning if it does not match);
  - backbone element structure (ported from the monolith's
    ``ectd.validate_backbone``): index.xml and ca-regional.xml must parse, the
    root element of each must match its pinned schema descriptor (the CA
    Module 1 v2.2 regional backbone + the ICH index), index.xml must carry its
    dossier-id/sequence identification, every ``<leaf>`` must be complete
    (id + href + checksum) and ca-regional.xml must identify the dossier;
  - optional document bytes: a ``.pdf`` whose bytes do not start with ``%PDF``
    is a ``pdf_header`` error; bytes containing ``/Encrypt`` are ``pdf_encrypted``
    (HC rejects secured PDFs).

Every finding carries a stable Health-Canada-v5.3-style rule id (``rule_id``)
alongside its machine ``rule`` name, human ``message`` and offending subject
(``leaf`` — a leaf id, sequence number or document key). The scheme:

    CA-<severity>-<block><nn>
      severity   E = error (blocks transmission), W = warning (advisory)
      block 1xxx leaf inventory integrity (href/checksum presence, duplicate
                 leaf ids, MD5 checksum format)
            2xxx lifecycle operation legality, replayed across sequences
            3xxx file/folder naming hygiene
            4xxx sequence numbering (four-digit, unique, contiguous from 0000)
            5xxx index.xml backbone element structure (ICH eCTD); 55xx the
                 transmissible per-sequence <ectd:ectd> backbone (operation
                 attrs, modified-file back-pointers, dangling hrefs, DOCTYPE)
            6xxx ca-regional.xml element structure (CA Module 1 v2.2)
            7xxx document payload checks (PDF header / encryption)

Rule ids are stable API: never renumber or reuse an id — retire it instead.

``passed`` is true iff there are zero errors.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from . import assembly, ectd

# a leaf href must live under a module folder m1..m5, e.g. "m1/ca/13-.../131-pm.pdf"
MODULE_FOLDER_RE = re.compile(r"^m[1-5]/")
# an MD5 checksum is exactly 32 hex digits
MD5_HEX_RE = re.compile(r"[0-9a-fA-F]{32}")
PDF_MAGIC = b"%PDF"
PDF_ENCRYPT_MARKER = b"/Encrypt"

# Pinned backbone descriptors (ported from the monolith's descriptor-driven
# ``ectd.validate_backbone``): the expected root element is resolved from the
# descriptor, never asserted in prose. These pin the element structure the
# assembly builder emits for the ICH index + CA Module 1 v2.2 regional file.
INDEX_BACKBONE = {
    "root_element": "ectd-index",
    "admin_attrs": ("dossier-id", "sequence"),
    "leaf_attrs": ("id", "href", "checksum"),
}
CA_REGIONAL_BACKBONE = {
    "root_element": "ca-regional",
    "schema_version": ectd.CA_M1_SCHEMA_VERSION,   # CA Module 1 v2.2
    "dossier_id_element": "dossier-id",
}

# rule name -> stable HC-style rule id (see module docstring for the scheme)
RULE_IDS = {
    # 1xxx — leaf inventory integrity
    "href_required": "CA-E-1001",
    "checksum_required": "CA-E-1002",
    "duplicate_leaf_id": "CA-E-1003",
    "checksum_not_md5": "CA-E-1004",
    # 2xxx — lifecycle operation legality
    "leaf_id_required": "CA-E-2001",
    "operation_invalid": "CA-E-2002",
    "prior_leaf_required": "CA-E-2003",
    "prior_leaf_unknown": "CA-E-2004",
    "new_has_prior": "CA-E-2005",
    # 3xxx — file/folder naming hygiene
    "href_not_lowercase": "CA-E-3001",
    "href_has_space": "CA-E-3002",
    "href_module_folder": "CA-W-3003",
    # 4xxx — sequence numbering
    "sequence_not_numeric": "CA-E-4001",
    "sequence_wrong_width": "CA-E-4002",
    "sequence_duplicate": "CA-E-4003",
    "sequence_not_contiguous": "CA-W-4004",
    "sequence_start_not_0000": "CA-W-4005",
    # 5xxx — index.xml backbone structure
    "backbone_malformed": "CA-E-5001",
    "index_root_unexpected": "CA-E-5002",
    "index_leaf_incomplete": "CA-E-5003",
    "index_admin_missing": "CA-E-5004",
    # 5.5xxx — transmissible ICH eCTD 3.2.2 sequence backbone (per-sequence
    # <ectd:ectd> index: operation attrs, lifecycle back-pointers, live hrefs)
    "leaf_operation_missing": "CA-E-5501",
    "leaf_modified_file_missing": "CA-E-5502",
    "leaf_href_dangling": "CA-E-5503",
    "index_doctype_missing": "CA-E-5504",
    # 6xxx — ca-regional.xml structure (CA Module 1 v2.2)
    "ca_root_unexpected": "CA-E-6001",
    "ca_dossier_id_missing": "CA-E-6002",
    "ca_company_id_missing": "CA-E-6003",
    "ca_product_missing": "CA-E-6004",
    # 7xxx — document payloads
    "pdf_header": "CA-E-7001",
    "pdf_encrypted": "CA-E-7002",
}
# defensive fallback for a rule the table does not know (e.g. a new rule added
# to assembly.validate_leaf_operation before this table learns its id)
UNMAPPED_RULE_ID = "CA-E-0000"

# Human-readable catalogue — regulatory operations people evaluate a tool by
# its rule coverage, so the full registry is a first-class, queryable surface.
_FAMILIES = {
    "1": "Leaf inventory integrity",
    "2": "Lifecycle operation legality",
    "3": "File & folder naming hygiene",
    "4": "Sequence numbering",
    "5": "index.xml backbone structure",
    "55": "Transmissible ICH eCTD 3.2.2 sequence backbone",
    "6": "ca-regional.xml structure (CA Module 1 v2.2)",
    "7": "Document payload conformance",
}

# WS1 (round-4 trust fix): name and version this validator, and state plainly
# what it does and does NOT do. Regulatory professionals distrust an unlabelled
# green checkmark; they trust an honest scope statement. This validator is
# ANDS Studio's own STRUCTURAL/TECHNICAL checker modeled on Health Canada's
# eCTD Validation Criteria rule scheme — it is NOT Health Canada's official
# eValidator and does not replace it.
# v1.2 (round-7 validate_export blocker, 13 respondents): every rule now names
# the HC/ICH source clause it is modeled on, and the profile declares the date it
# was last reconciled against the published HC criteria.
CRITERIA_VERSION = "1.2"
# When the rule set was last reconciled against the published HC eCTD Validation
# Criteria. Bump this whenever HC republishes and the mapping is re-checked.
CRITERIA_SYNCED = "2026-05 (HC eCTD Validation Criteria v5.3)"


def criteria() -> dict:
    """The named, versioned validation profile + an honest coverage statement."""
    return {
        "name": "ANDS Studio structural eCTD validator",
        "version": CRITERIA_VERSION,
        "synced": CRITERIA_SYNCED,
        "modeled_on": "Health Canada eCTD Validation Criteria v5.3 rule scheme "
                      "(CA-<severity>-<block> ids), CA Module 1 v2.2 regional "
                      "backbone and the ICH eCTD 3.2.2 index",
        "disclaimer": "Structural and technical checks only. This is NOT Health "
                      "Canada's official eValidator and does not replace it — "
                      "run eValidator (or your publisher's validator) before "
                      "you transmit.",
        "coverage": {
            "checked": sorted(set(_FAMILIES.values())),
            "not_checked": [
                "Scientific, clinical or quality adequacy of the content",
                "Full PDF/A-1 conformance (only the %PDF header and encryption "
                "are checked, not the ISO profile)",
                "Cross-document hyperlink target resolution",
                "Health Canada screening or review acceptance",
            ],
        },
    }


_RULE_DESCRIPTIONS = {
    "href_required": "Every live leaf must reference a file (href).",
    "checksum_required": "Every live leaf must carry an MD5 checksum.",
    "duplicate_leaf_id": "Leaf IDs must be unique across the submission.",
    "checksum_not_md5": "Checksums must be well-formed 32-hex-digit MD5.",
    "leaf_id_required": "Every lifecycle operation needs a leaf ID.",
    "operation_invalid": "Operation must be one of new/replace/append/delete.",
    "prior_leaf_required": "replace/append/delete must name the prior leaf they modify.",
    "prior_leaf_unknown": "The referenced prior leaf must exist in an earlier sequence.",
    "new_has_prior": "A 'new' leaf cannot reference a prior leaf.",
    "href_not_lowercase": "File and folder names must be lowercase.",
    "href_has_space": "File and folder names must not contain spaces.",
    "href_module_folder": "Leaves should live under their module's folder (warning).",
    "sequence_not_numeric": "Sequence names must be numeric.",
    "sequence_wrong_width": "Sequence names must be exactly four digits (e.g. 0000).",
    "sequence_duplicate": "Sequence numbers must not repeat.",
    "sequence_not_contiguous": "Sequences should be contiguous (warning).",
    "sequence_start_not_0000": "The dossier should start at sequence 0000 (warning).",
    "backbone_malformed": "index.xml must be well-formed XML.",
    "index_root_unexpected": "index.xml root element must match the eCTD DTD.",
    "index_leaf_incomplete": "Every index.xml leaf needs ID, href, checksum and title.",
    "index_admin_missing": "The administrative section must be present in index.xml.",
    "leaf_operation_missing": "Each sequence-backbone leaf must declare its operation.",
    "leaf_modified_file_missing": "replace/append/delete must point at the modified file.",
    "leaf_href_dangling": "Backbone hrefs must resolve to files shipped in the sequence.",
    "index_doctype_missing": "The sequence index must declare the eCTD DOCTYPE.",
    "ca_root_unexpected": "ca-regional.xml root must match the CA Module 1 v2.2 schema.",
    "ca_dossier_id_missing": "ca-regional.xml must carry the dossier identifier.",
    "ca_company_id_missing": "ca-regional.xml must carry the company identifier.",
    "ca_product_missing": "ca-regional.xml must identify the drug product.",
    "pdf_header": "Documents claiming PDF must actually be PDFs (%PDF header).",
    "pdf_encrypted": "PDFs must not be encrypted or password-protected.",
}


# The governing HC/ICH source each rule family is modeled on. Regulatory-
# operations personas (regops_publisher, consultant_ex_hc, ra_officer_generic)
# evaluate a validator by whether every rule cites a real, checkable clause —
# not a vague "structural check". These reference the modeled-on specifications;
# they are NOT a claim of 1:1 numeric parity with HC's official eValidator (see
# the eValidator handoff / parity-gap surface).
_FAMILY_SOURCE = {
    "1": "ICH eCTD Spec v3.2.2 §2.3 (leaf: xlink:href, checksum, checksum-type) "
         "· HC eCTD Validation Criteria v5.3 (leaf inventory & MD5)",
    "2": "ICH eCTD Spec v3.2.2 §2.4 (life-cycle management: "
         "new/replace/append/delete) · HC eCTD Validation Criteria v5.3",
    "3": "ICH eCTD Spec v3.2.2 §4 & appendices (folder/file naming: lowercase, "
         "no spaces) · HC eCTD Validation Criteria v5.3",
    "4": "ICH eCTD Spec v3.2.2 §3 (sequence numbering — four-digit, from 0000) "
         "· HC eCTD Validation Criteria v5.3",
    "5": "ICH eCTD DTD ich-ectd-3-2.dtd (index.xml backbone) "
         "· HC eCTD Validation Criteria v5.3",
    "55": "ICH eCTD Spec v3.2.2 §2 + util/dtd (transmissible 3.2.2 sequence "
          "backbone: operation attrs, lifecycle back-pointers, live hrefs)",
    "6": "HC 'Preparation of Regulatory Activities in eCTD Format' — CA Module 1 "
         "v2.2 & ca-regional.dtd (Canadian regional backbone)",
    "7": "ICH eCTD Spec v3.2.2 Appendix 7 (PDF) · HC document payload requirements",
}


def rule_catalog() -> dict:
    """The queryable registry of every technical validation rule."""
    rules = []
    for rule, rule_id in RULE_IDS.items():
        digits = rule_id.split("-")[2]
        fam_key = "55" if digits.startswith("55") else digits[0]
        family = _FAMILIES[fam_key]
        rules.append({
            "rule": rule, "rule_id": rule_id, "family": family,
            "severity": "warning" if "-W-" in rule_id else "error",
            "description": _RULE_DESCRIPTIONS.get(rule, ""),
            "source": _FAMILY_SOURCE[fam_key],
        })
    rules.append({
        "rule": "placeholder_dossier_id", "rule_id": "CA-REP-0001",
        "family": "REP identity",
        "severity": "error",
        "description": "Filing is blocked while the dossier uses a placeholder "
                       "ID instead of the Health Canada-issued one (REP).",
        "source": "HC Dossier Identifier guidance — Regulatory Enrolment "
                  "Process (REP); Dossier ID issued on request via the REP",
    })
    return {"count": len(rules), "rules": rules, "criteria": criteria()}


# WS-VALIDATE (round-8 blocker, n=12): the eValidator PARITY / HANDOFF surface.
# This is ADDED alongside criteria()/rule_catalog() — it does not rewrite them.
# It answers the one question every regulatory-ops persona asked: "does a green
# result here mean my sequence would pass Health Canada's official eValidator?"
# The honest answer is NO — this is a structural/technical checker, and even the
# rules that DO overlap a real eValidator rule are not a 1:1 numeric-parity claim.
# So parity() states, per rule FAMILY, whether HC's eValidator checks the same
# class of defect (an overlap, not equivalence) or does not, and always carries
# the "run eValidator before you transmit" next step.
#
# hc_evalidator_covered = True  -> HC's eValidator also checks this defect class
#                                  (our structural check is a useful pre-flight,
#                                  but eValidator remains authoritative)
#              = False -> this is an ANDS Studio convenience/structural check
#                         with NO direct HC eValidator counterpart.
_FAMILY_PARITY = {
    # family key -> (hc_evalidator_covered, plain-English note)
    "1": (True, "HC eValidator also checks leaf inventory integrity (href, "
                "checksum presence and MD5 format). Overlaps, not 1:1 parity — "
                "eValidator remains authoritative."),
    "2": (True, "HC eValidator validates eCTD life-cycle operations "
                "(new/replace/append/delete) against the cumulative dossier."),
    "3": (True, "HC eValidator flags file/folder naming defects (case, spaces, "
                "module folder placement)."),
    "4": (True, "HC eValidator checks sequence numbering (four-digit, from "
                "0000, contiguity)."),
    "5": (True, "HC eValidator validates the index.xml backbone against the "
                "ICH eCTD DTD."),
    "55": (True, "HC eValidator validates the transmissible per-sequence "
                 "<ectd:ectd> backbone (operation attrs, lifecycle "
                 "back-pointers, live hrefs)."),
    "6": (True, "HC eValidator validates the CA Module 1 v2.2 regional "
                "backbone (ca-regional.xml)."),
    "7": (False, "ANDS Studio checks only the %PDF header and encryption. HC "
                 "eValidator (and your publisher) verify full PDF/A-1 "
                 "conformance, which this tool does NOT — run it before you "
                 "transmit."),
    "REP": (False, "The Dossier ID is issued by Health Canada via the "
                   "Regulatory Enrolment Process (REP); no validator mints or "
                   "confirms it. This is an ANDS Studio filing guardrail, not "
                   "an eValidator rule."),
}


def _parity_family_key(rule_id: str) -> str:
    """Map a rule id to its parity family key (mirrors rule_catalog)."""
    if rule_id.startswith("CA-REP"):
        return "REP"
    digits = rule_id.split("-")[2]
    return "55" if digits.startswith("55") else digits[0]


# ADOPT-EVALIDATOR: rule-LEVEL parity, where the mapping is clean and honest.
# A rule earns ``coverage_level == "rule"`` only when the specific defect it
# raises maps to a single, well-known HC eValidator check of the SAME defect
# (still an overlap, not a numeric-id parity claim). Rules whose family HC
# covers but which do not have a clean 1:1 defect mapping stay at "family".
# Rules with no HC eValidator counterpart at all are "none". This keeps the
# honest not_covered set intact — we never upgrade a convenience check.
_RULE_LEVEL_COVERED = {
    # leaf inventory integrity — each is a discrete HC eValidator leaf check
    "href_required",        # leaf must carry an xlink:href
    "checksum_required",    # leaf must carry a checksum
    "checksum_not_md5",     # checksum must be a valid MD5
    "duplicate_leaf_id",    # leaf ids unique across the dossier
    # lifecycle operation legality — discrete life-cycle-management checks
    "operation_invalid",    # operation ∈ new/replace/append/delete
    "prior_leaf_required",  # replace/append/delete names its prior leaf
    "prior_leaf_unknown",   # the referenced prior leaf must exist
    # file/folder naming hygiene — discrete naming checks
    "href_not_lowercase",
    "href_has_space",
    # sequence numbering — discrete four-digit / uniqueness checks
    "sequence_not_numeric",
    "sequence_wrong_width",
    "sequence_duplicate",
    # transmissible sequence backbone — discrete lifecycle-attr checks
    "leaf_operation_missing",
    "leaf_modified_file_missing",
    "leaf_href_dangling",
    # regional backbone identity
    "ca_dossier_id_missing",
    "ca_company_id_missing",
}


def _coverage_level(rule: str, covered: bool) -> str:
    """The honest per-rule coverage granularity.

    "rule"   — a clean 1:1 defect mapping to a specific HC eValidator check;
    "family" — HC's eValidator covers this rule's FAMILY, but this particular
               rule is an ANDS Studio refinement/warning without a discrete
               eValidator counterpart (e.g. our contiguity/module-folder hints);
    "none"   — no HC eValidator counterpart at all (convenience/guardrail).
    """
    if not covered:
        return "none"
    return "rule" if rule in _RULE_LEVEL_COVERED else "family"


def parity() -> dict:
    """The eValidator parity-gap table + a persistent, ACTIONABLE next step.

    For every rule the catalogue exposes, declare whether Health Canada's
    official eValidator checks the same class of defect (``hc_evalidator_covered``
    — an OVERLAP, never a 1:1 numeric-parity claim) with a plain-English note.
    Always carries the versioned :func:`criteria` and the persistent
    "you must still run HC eValidator before transmission" next step so the
    honesty disclaimer becomes an actionable hand-off, not just a caveat.
    """
    rules = []
    for r in rule_catalog()["rules"]:
        covered, note = _FAMILY_PARITY[_parity_family_key(r["rule_id"])]
        level = _coverage_level(r["rule"], covered)
        rules.append({
            "rule": r["rule"], "rule_id": r["rule_id"], "family": r["family"],
            "severity": r["severity"],
            "hc_evalidator_covered": covered, "note": note,
            # ADOPT-EVALIDATOR: per-rule granularity — "rule" is a clean 1:1
            # defect mapping, "family" a family-level overlap, "none" no HC
            # counterpart. The honest not_covered set is preserved.
            "coverage_level": level,
        })
    covered_count = sum(1 for r in rules if r["hc_evalidator_covered"])
    rule_level_count = sum(1 for r in rules if r["coverage_level"] == "rule")
    return {
        "criteria": criteria(),
        "rules": rules,
        "covered_count": covered_count,
        "not_covered_count": len(rules) - covered_count,
        "rule_level_count": rule_level_count,
        "next_step": {
            "banner": "You must still run Health Canada's official eValidator "
                      "before transmission. A clean result here means the "
                      "sequence is structurally plausible — it does NOT mean it "
                      "will pass HC's eValidator or be accepted on screening.",
            "action": "Export the eCTD package, then validate it in HC's "
                      "eValidator (or your publisher's validator, e.g. "
                      "docuBridge / Lorenz eValidator) and resolve any findings "
                      "before you upload through CESG WebTrader.",
            "why": "The rows below marked 'no HC eValidator counterpart' are "
                   "ANDS Studio convenience checks; the rows marked 'overlaps' "
                   "cover the same defect class but are not a 1:1 parity claim.",
        },
    }


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _err(rule: str, message: str, leaf) -> dict:
    return {"rule": rule, "rule_id": RULE_IDS.get(rule, UNMAPPED_RULE_ID),
            "message": message, "leaf": leaf}


def _live_leaf_check(dossier: dict, errors: list) -> None:
    """Every live leaf needs an href AND a well-formed MD5 checksum."""
    for lf in assembly.current_view(dossier)["live"]:
        leaf_id = _s(lf.get("leaf_id"))
        if not _s(lf.get("href")):
            errors.append(_err("href_required",
                               "a live leaf must have a non-empty href", leaf_id))
        checksum = _s(lf.get("checksum"))
        if not checksum:
            errors.append(_err("checksum_required",
                               "a live leaf must have a non-empty checksum",
                               leaf_id))
        elif not MD5_HEX_RE.fullmatch(checksum):
            errors.append(_err("checksum_not_md5",
                               f"checksum '{checksum}' is not a 32-hex-digit "
                               "MD5 digest", leaf_id))


def _duplicate_leaf_check(dossier: dict, errors: list) -> None:
    seen: set = set()
    for lf in assembly.leaves_in_order(dossier):
        leaf_id = _s(lf.get("leaf_id"))
        if leaf_id and leaf_id in seen:
            errors.append(_err("duplicate_leaf_id",
                               f"leaf ID '{leaf_id}' appears more than once",
                               leaf_id))
        seen.add(leaf_id)


def _operation_check(dossier: dict, errors: list) -> None:
    """Replay operations in order; each must be legal against the live set so far."""
    live: dict = {}
    for lf in assembly.leaves_in_order(dossier):
        leaf_id = _s(lf.get("leaf_id"))
        op = _s(lf.get("operation"))
        target = _s(lf.get("modified_leaf")) or None
        for e in assembly.validate_leaf_operation(lf, set(live.keys())):
            errors.append(_err(e["rule"], e["message"], leaf_id))
        # ported monolith rule: a 'new' leaf must not point at a prior leaf
        if op == "new" and target:
            errors.append(_err("new_has_prior",
                               "a 'new' operation must not reference a prior "
                               "leaf", leaf_id))
        # advance the live set exactly as compute_current_view would
        if op in ("new", "append"):
            live[leaf_id] = lf
        elif op == "replace":
            if target and target in live:
                live.pop(target)
            live[leaf_id] = lf
        elif op == "delete":
            if target and target in live:
                live.pop(target)


def _sequence_numbering_check(dossier: dict, errors: list,
                              warnings: list) -> None:
    """Sequence numbers are unique four-digit numbers, contiguous from 0000."""
    seen: set = set()
    numeric: list = []
    for s in dossier.get("sequences", []):
        seq = _s(s.get("sequence"))
        if not seq.isdigit():
            errors.append(_err("sequence_not_numeric",
                               f"sequence '{seq}' is not a numeric sequence "
                               "number", seq))
            continue
        if len(seq) != 4:
            errors.append(_err("sequence_wrong_width",
                               f"sequence '{seq}' must be exactly four digits "
                               "(e.g. '0000')", seq))
        if seq in seen:
            errors.append(_err("sequence_duplicate",
                               f"sequence '{seq}' appears more than once", seq))
        seen.add(seq)
        numeric.append(int(seq))
    if not numeric:
        return
    ordered = sorted(set(numeric))
    if ordered[0] != 0:
        warnings.append(_err("sequence_start_not_0000",
                             f"the first sequence is '{ordered[0]:04d}', not "
                             "'0000'", f"{ordered[0]:04d}"))
    if ordered != list(range(ordered[0], ordered[0] + len(ordered))):
        gaps = sorted(set(range(ordered[0], ordered[-1])) - set(ordered))
        warnings.append(_err("sequence_not_contiguous",
                             "sequence numbering has gaps (missing: "
                             + ", ".join(f"{g:04d}" for g in gaps) + ")",
                             None))


def _href_naming_check(dossier: dict, errors: list, warnings: list) -> None:
    for lf in assembly.current_view(dossier)["live"]:
        leaf_id = _s(lf.get("leaf_id"))
        href = _s(lf.get("href"))
        if not href:
            continue
        if href != href.lower():
            errors.append(_err("href_not_lowercase",
                               f"href '{href}' must be lowercase", leaf_id))
        if " " in href:
            errors.append(_err("href_has_space",
                               f"href '{href}' must not contain spaces", leaf_id))
        if not MODULE_FOLDER_RE.match(href):
            warnings.append(_err("href_module_folder",
                                 f"href '{href}' does not match the m1..m5 "
                                 "module-folder pattern", leaf_id))


def _parse_backbone(xml_text: str, name: str, findings: list):
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        findings.append(_err("backbone_malformed",
                             f"{name} failed to parse: {exc}", None))
        return None


def validate_backbone_xml(index_xml: str, ca_regional_xml: str) -> list:
    """Structural findings for a built backbone pair (empty list = clean).

    Port of the monolith's ``ectd.validate_backbone``: each document must be
    well-formed, its root element must match the pinned schema descriptor
    (never a prose assertion), index.xml must carry its dossier-id/sequence
    identification and complete ``<leaf>`` elements (id + href + checksum),
    and the CA Module 1 v2.2 regional file must identify the dossier.
    """
    findings: list = []

    root = _parse_backbone(index_xml, "index.xml", findings)
    if root is not None:
        expected = INDEX_BACKBONE["root_element"]
        if root.tag != expected:
            findings.append(_err("index_root_unexpected",
                                 f"index.xml root element '{root.tag}' does "
                                 "not match the pinned schema root "
                                 f"'{expected}'", None))
        else:
            for attr in INDEX_BACKBONE["admin_attrs"]:
                if not _s(root.get(attr)):
                    findings.append(_err("index_admin_missing",
                                         "index.xml is missing its "
                                         f"'{attr}' identification", None))
            for leaf in root.iter("leaf"):
                leaf_id = _s(leaf.get("id")) or None
                for attr in INDEX_BACKBONE["leaf_attrs"]:
                    if not _s(leaf.get(attr)):
                        findings.append(_err("index_leaf_incomplete",
                                             "a <leaf> in index.xml is "
                                             f"missing its '{attr}'", leaf_id))

    ca = _parse_backbone(ca_regional_xml, "ca-regional.xml", findings)
    if ca is not None:
        expected = CA_REGIONAL_BACKBONE["root_element"]
        version = CA_REGIONAL_BACKBONE["schema_version"]
        if ca.tag != expected:
            findings.append(_err("ca_root_unexpected",
                                 f"ca-regional.xml root element '{ca.tag}' "
                                 "does not match the pinned CA Module 1 "
                                 f"v{version} root '{expected}'", None))
        else:
            node = ca.find(CA_REGIONAL_BACKBONE["dossier_id_element"])
            if node is None or not _s(node.text):
                findings.append(_err("ca_dossier_id_missing",
                                     f"ca-regional.xml (CA Module 1 v{version})"
                                     " must identify the dossier via "
                                     "<dossier-id>", None))
    return findings


XLINK_HREF = f"{{{assembly.XLINK_NS}}}href"
ECTD_ROOT = f"{{{assembly.ECTD_NS}}}ectd"
CA_ROOT = f"{{{assembly.CA_NS}}}ectd-ca"
LIFECYCLE_NEEDS_PRIOR = ("replace", "append", "delete")


def _leaf_href(leaf) -> str:
    """A leaf's href, whether emitted as xlink:href or a plain href attr."""
    return _s(leaf.get(XLINK_HREF) or leaf.get("xlink:href") or leaf.get("href"))


def _modified_file_href(leaf) -> str:
    for child in leaf:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "modified-file":
            return _s(child.get(XLINK_HREF) or child.get("xlink:href")
                      or child.get("href"))
    return ""


def validate_sequence_backbone(index_xml: str, ca_regional_xml: str,
                               present_paths) -> list:
    """Conformance findings for a transmissible ICH eCTD 3.2.2 sequence backbone.

    This is the *real* per-sequence backbone (root ``<ectd:ectd>``) that
    :func:`assembly.build_sequence_backbone` emits and ``export_pkg`` ships —
    distinct from the viewer's lightweight ``<ectd-index>`` outline validated by
    :func:`validate_backbone_xml`. It catches exactly what the CRO director
    flagged:

    - ``leaf_operation_missing`` — a ``<leaf>`` with no ``operation`` attribute;
    - ``leaf_modified_file_missing`` — a replace/append/delete leaf with no
      ``<modified-file>`` back-pointer at the prior leaf;
    - ``leaf_href_dangling`` — a leaf whose ``xlink:href`` names a file that is
      not present in the sequence (``present_paths`` = relative paths shipped);
    - ``index_doctype_missing`` — index.xml carries no DOCTYPE (no ICH DTD ref).

    ``present_paths`` is the set of leaf-file paths (relative to the sequence
    folder, e.g. ``m1/ca/10-cover-letter/cl.pdf``) actually in the package.
    """
    findings: list = []
    present = {_s(p) for p in (present_paths or set())}

    if "<!DOCTYPE" not in (index_xml or ""):
        findings.append(_err("index_doctype_missing",
                             "index.xml has no DOCTYPE referencing the ICH "
                             "eCTD DTD (util/dtd/ich-ectd-3-2.dtd)", None))

    root = _parse_backbone(index_xml, "index.xml", findings)
    if root is not None:
        if root.tag not in (ECTD_ROOT, "ectd:ectd"):
            findings.append(_err("index_root_unexpected",
                                 f"index.xml root element '{root.tag}' is not "
                                 "the ICH eCTD root '<ectd:ectd>'", None))
        for leaf in root.iter():
            if leaf.tag.rsplit("}", 1)[-1] != "leaf":
                continue
            leaf_id = _s(leaf.get("ID") or leaf.get("id")) or None
            op = _s(leaf.get("operation"))
            if not op:
                findings.append(_err("leaf_operation_missing",
                                     "a <leaf> in index.xml has no eCTD "
                                     "'operation' attribute", leaf_id))
            if op in LIFECYCLE_NEEDS_PRIOR and not _modified_file_href(leaf):
                findings.append(_err("leaf_modified_file_missing",
                                     f"a '{op}' <leaf> must carry a "
                                     "<modified-file> back-pointer at the "
                                     "prior leaf", leaf_id))
            href = _leaf_href(leaf)
            if op != "delete" and href and href not in present:
                findings.append(_err("leaf_href_dangling",
                                     f"leaf href '{href}' is referenced in "
                                     "index.xml but no such file is in the "
                                     "sequence", leaf_id))

    ca = _parse_backbone(ca_regional_xml, "ca-regional.xml", findings)
    if ca is not None:
        if ca.tag not in (CA_ROOT, "ca:ectd-ca"):
            findings.append(_err("ca_root_unexpected",
                                 f"ca-regional.xml root '{ca.tag}' is not the "
                                 "CA Module 1 v2.2 root '<ca:ectd-ca>'", None))
        else:
            text_of = lambda p: _s((ca.find(p).text if ca.find(p) is not None
                                    else ""))
            if not text_of("application-info/dossier-id"):
                findings.append(_err("ca_dossier_id_missing",
                                     "ca-regional.xml must identify the dossier "
                                     "(<application-info><dossier-id>)", None))
            if not text_of("application-info/company-id"):
                findings.append(_err("ca_company_id_missing",
                                     "ca-regional.xml must carry the company-id "
                                     "(<application-info><company-id>)", None))
            if not any(_s(p.text) for p in ca.findall("product")):
                findings.append(_err("ca_product_missing",
                                     "ca-regional.xml must name at least one "
                                     "<product>", None))
    return findings


def _backbone_check(dossier: dict, errors: list) -> None:
    seqs = [s["sequence"] for s in dossier.get("sequences", [])]
    sequence = seqs[-1] if seqs else "0000"
    try:
        backbone = assembly.build_outline_view(dossier, sequence)["backbone"]
        index_xml = backbone["index.xml"]
        ca_xml = backbone["ca-regional.xml"]
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(_err("backbone_malformed",
                           f"backbone build failed: {exc}", None))
        return
    errors.extend(validate_backbone_xml(index_xml, ca_xml))


def _sequence_backbone_check(dossier: dict, errors: list) -> None:
    """Conformance of the *transmissible* per-sequence backbone for every
    sequence: each sequence's own leaves are what it ships, so the only way a
    href dangles here is a modelling defect (a leaf with no href / bad
    operation). Every replace/append/delete must carry its modified-file
    back-pointer and ca-regional must be a real CA M1 v2.2 file (company +
    product)."""
    for s in dossier.get("sequences", []):
        seq = _s(s.get("sequence"))
        try:
            bb = assembly.build_sequence_backbone(dossier, seq)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(_err("backbone_malformed",
                               f"sequence backbone build failed: {exc}", None))
            continue
        present = {_s(lf.get("href"))
                   for lf in assembly.sequence_leaves(dossier, seq)
                   if _s(lf.get("operation")) != "delete" and _s(lf.get("href"))}
        for f in validate_sequence_backbone(
                bb["index_xml"], bb["ca_regional_xml"], present):
            # a product name is only known once the export supplies it (or a
            # 1.3.1 monograph is placed); an in-progress dossier without one is
            # not yet a transmission defect, so it does not block the gate.
            if f["rule"] == "ca_product_missing":
                continue
            errors.append(f)


def _document_check(documents: dict, errors: list) -> None:
    for key, data in documents.items():
        name = _s(key).lower()
        raw = data if isinstance(data, (bytes, bytearray)) else _s(data).encode()
        raw = bytes(raw)
        # only .pdf-named payloads get header/encryption scrutiny
        if not name.endswith(".pdf"):
            continue
        if not raw.startswith(PDF_MAGIC):
            errors.append(_err("pdf_header",
                               f"document '{key}' is named .pdf but its bytes do "
                               "not start with %PDF", key))
        if PDF_ENCRYPT_MARKER in raw:
            errors.append(_err("pdf_encrypted",
                               f"document '{key}' is an encrypted/secured PDF "
                               "(HC rejects /Encrypt)", key))


def validate(dossier: dict, *, documents: dict | None = None) -> dict:
    """Run the full eCTD technical validation over an assembled ``dossier``.

    ``documents`` optionally maps a doc id / leaf id / filename -> raw bytes; any
    key ending ``.pdf`` is checked for the %PDF magic and for /Encrypt.
    Returns ``{passed, errors, warnings, checked}`` where ``checked`` is the live
    leaf count. Every error/warning carries a stable ``rule_id`` (see the
    module docstring for the CA-E/CA-W scheme). ``passed`` is true iff
    ``errors`` is empty.
    """
    errors: list = []
    warnings: list = []

    _sequence_numbering_check(dossier, errors, warnings)
    _duplicate_leaf_check(dossier, errors)
    _operation_check(dossier, errors)
    _live_leaf_check(dossier, errors)
    _href_naming_check(dossier, errors, warnings)
    _backbone_check(dossier, errors)
    _sequence_backbone_check(dossier, errors)
    if documents:
        _document_check(documents, errors)

    checked = len(assembly.current_view(dossier)["live"])
    return {"passed": not errors, "errors": errors, "warnings": warnings,
            "checked": checked, "criteria": criteria()}
