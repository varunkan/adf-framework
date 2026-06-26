#!/usr/bin/env python3
"""
ANDS Submission Portal — Q&A response-sequence builder (REQ-032).

The *issuing* side of a deficiency notice lives in ``lifecycle.py`` (HC issues an
SDN / clarifax / NOD / NON). This module is the sponsor *response* side: given an
original notice and a set of Q&A answers, it assembles the sponsor's reply and
files it as a **new eCTD sequence** in the **same format** (eCTD) as the original
dossier.

REQ-032 — "a Q&A-format response-sequence builder that attaches the original
notice (SDN/clarifax/NOD/NON), authors answers referencing the applicable
submission sections, and files the response as a new eCTD sequence in the same
format as the original."

Acceptance criteria:
  1. starting a response attaches a COPY of the original notice to the new
     sequence (a ``new`` leaf carrying the notice bytes);
  2. each authored answer REFERENCES the applicable submission section (the
     answer leaf is placed at / points to that section's eCTD heading);
  3. filing produces the NEXT valid eCTD sequence number for the dossier, built
     in the same eCTD format (index.xml + ca-regional backbones).

Pure-stdlib, dependency-free and deterministic; mirrors the one-concern-per-
module style of ``lifecycle.py`` / ``rep.py`` and reuses ``ectd.Dossier`` for the
actual sequence/leaf/backbone machinery so nothing about the eCTD format is
re-implemented.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _xml_escape

import ectd

# The notice kinds a sponsor can respond to (mirrors
# ``lifecycle.RESPONSE_TIMER_KINDS``; kept independent so this module does not
# require a live ``Lifecycle`` to build a response).
RESPONSE_NOTICE_KINDS = frozenset({"SDN", "clarifax", "NOD", "NON"})

# Where the attached copy of the original notice and the Q&A answer document are
# placed inside the new eCTD sequence. Both land under Module 1 administrative
# information (1.2), the eCTD home for correspondence and responses.
NOTICE_HEADING = "1.2"
ANSWERS_HEADING = "1.2"


class ResponseBuilderError(Exception):
    """Raised for an invalid Q&A response-sequence build (REQ-032)."""


def _e(value) -> str:
    """XML-escape a value (mirrors ``rep._e`` / ``ectd`` escaping idioms)."""
    return _xml_escape(str(value if value is not None else "").strip())


def _seq_int(sequence: str) -> int:
    """The integer value of a 4-digit eCTD sequence folder (e.g. '0003' -> 3)."""
    text = str(sequence or "").strip()
    return int(text) if text.isdigit() else 0


def next_sequence_number(dossier: "ectd.Dossier") -> str:
    """REQ-032 (AC3): the next valid 4-digit eCTD sequence for a dossier.

    eCTD sequences are monotonic 4-digit folders. The next one is
    ``max(existing) + 1`` zero-padded to four digits (or ``0000`` for the first
    sequence). Same numbering rule the dossier already uses, so a filed response
    slots in as the next legitimate sequence.
    """
    existing = [_seq_int(s) for s in dossier.sequence_numbers()]
    nxt = (max(existing) + 1) if existing else 0
    if nxt > 9999:
        raise ResponseBuilderError(
            "eCTD sequence numbers are exhausted (max 9999)")
    return f"{nxt:04d}"


def normalize_kind(kind: str) -> str:
    """Normalise a notice kind to its canonical token (case-insensitive).

    ``SDN``/``NOD``/``NON`` are upper-cased acronyms; ``clarifax`` is lower-case.
    """
    text = str(kind or "").strip()
    upper = text.upper()
    if upper in {"SDN", "NOD", "NON"}:
        return upper
    if upper == "CLARIFAX":
        return "clarifax"
    return text


def build_notice_copy(notice: dict) -> dict:
    """REQ-032 (AC1): a faithful COPY of the original notice for attachment.

    The returned dict carries the notice kind, its identifier and a verbatim copy
    of its text/bytes — this is what gets shipped as a ``new`` leaf in the new
    response sequence so the reply is self-contained.
    """
    notice = notice or {}
    kind = normalize_kind(notice.get("kind", ""))
    if kind not in RESPONSE_NOTICE_KINDS:
        raise ResponseBuilderError(
            f"notice kind must be one of {sorted(RESPONSE_NOTICE_KINDS)}; "
            f"got {notice.get('kind')!r}")
    content = notice.get("content")
    if content is None:
        content = notice.get("text", "")
    return {
        "kind": kind,
        "notice_id": str(notice.get("notice_id", "") or "").strip(),
        "issued_at": str(notice.get("issued_at", "") or "").strip(),
        "content": str(content),
        "is_copy": True,
    }


def build_answers_document(notice_copy: dict, answers: list) -> str:
    """REQ-032 (AC2): render the Q&A document.

    Each answer must reference the applicable submission section; the rendered
    document threads that reference next to every answer so a reviewer sees,
    per question, exactly which section of the dossier the response touches.
    """
    parts = [
        "Q&A Response to "
        f"{notice_copy.get('kind', 'notice')} "
        f"{notice_copy.get('notice_id', '')}".strip(),
        "=" * 60,
        "",
    ]
    for i, qa in enumerate(answers, start=1):
        section = str((qa or {}).get("section", "") or "").strip()
        question = str((qa or {}).get("question", "") or "").strip()
        answer = str((qa or {}).get("answer", "") or "").strip()
        parts.append(f"Q{i}. {question}")
        parts.append(f"    Applicable submission section: {section}")
        parts.append(f"    A{i}. {answer}")
        parts.append("")
    return "\n".join(parts) + "\n"


def validate_answers(answers: list) -> list:
    """REQ-032 (AC2): every answer MUST reference an applicable submission section.

    Returns one ``{"rule","message"}`` per offending answer (empty when clean).
    An empty answer set is itself an error — a response with no answers is not a
    Q&A response.
    """
    errors: list = []
    if not answers:
        errors.append({"rule": "answers_required",
                       "message": "a Q&A response needs at least one answer"})
        return errors
    for i, qa in enumerate(answers, start=1):
        qa = qa or {}
        if not str(qa.get("section", "") or "").strip():
            errors.append({
                "rule": "answer_section_required",
                "message": (f"answer {i} must reference the applicable "
                            "submission section")})
        if not str(qa.get("answer", "") or "").strip():
            errors.append({
                "rule": "answer_text_required",
                "message": f"answer {i} has no answer text"})
    return errors


def file_response_sequence(dossier: "ectd.Dossier", notice: dict,
                           answers: list, *, sequence: str = None) -> dict:
    """REQ-032: build + file a Q&A response as the next eCTD sequence.

    Mutates ``dossier`` in place, adding a NEW sequence that contains:
      * a leaf carrying a COPY of the original notice (AC1), and
      * one answer leaf per Q&A entry, each placed at / referencing the
        applicable submission section (AC2);
    and returns the filed eCTD sequence — built in the same eCTD format
    (index.xml + ca-regional backbones) as the original (AC3).

    Raises ``ResponseBuilderError`` on an invalid notice or answer set; the
    dossier is left unchanged in that case (validation runs before any mutation).
    """
    notice_copy = build_notice_copy(notice)          # validates the notice (AC1)
    errors = validate_answers(answers)               # validates the answers (AC2)
    if errors:
        raise ResponseBuilderError(errors[0]["message"])

    seq = (str(sequence).strip() if sequence not in (None, "")
           else next_sequence_number(dossier))       # next valid sequence (AC3)
    dossier.add_sequence(seq)

    # AC1 — attach a copy of the original notice as a new leaf.
    notice_leaf_id = f"resp-{seq}-notice"
    dossier.add_leaf(seq, {
        "leaf_id": notice_leaf_id,
        "operation": "new",
        "heading": NOTICE_HEADING,
        "title": (f"Original {notice_copy['kind']} notice "
                  f"{notice_copy['notice_id']}").strip(),
        "content": notice_copy["content"],
    })

    # AC2 — one answer leaf per Q&A entry, each referencing its section.
    answer_leaves = []
    for i, qa in enumerate(answers, start=1):
        section = str((qa or {}).get("section", "") or "").strip()
        leaf = dossier.add_leaf(seq, {
            "leaf_id": f"resp-{seq}-a{i}",
            "operation": "new",
            "heading": ANSWERS_HEADING,
            "title": f"Q&A answer {i} (re section {section})",
            "content": build_answers_document(notice_copy, [qa]),
        })
        # Tag the originating submission section so a reviewer / the API can
        # see, per answer, which section of the dossier it addresses (AC2).
        leaf["section_ref"] = section
        answer_leaves.append({"leaf_id": leaf["leaf_id"],
                              "section_ref": section,
                              "heading": leaf["heading"]})

    # AC3 — file in the SAME eCTD format: build the backbones for the sequence.
    built = dossier.build_backbones(seq)

    return {
        "dossier_id": dossier.dossier_id,
        "sequence": seq,
        "format": "eCTD",
        "notice": notice_copy,
        "notice_leaf_id": notice_leaf_id,
        "answers": answer_leaves,
        "answers_document": build_answers_document(notice_copy, answers),
        "files": built["files"],
        "index_md5": built["index_md5"],
    }
