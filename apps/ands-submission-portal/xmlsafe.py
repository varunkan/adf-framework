"""Hardened XML parsing shared across every module that parses caller-supplied
XML (Python stdlib only).

Several endpoints parse XML that did NOT originate inside the portal — an
``index.xml`` / ``ca-regional.xml`` posted to ``/api/validation/run`` or
``/api/validation/package-attempt``, a generated REP artifact, or an STF body
posted to ``/api/stf/validate``. Python's stdlib ``xml.dom.minidom``/expat does
NOT defend against a maliciously crafted document: a tiny "billion laughs"
payload of nested internal ``<!ENTITY>`` declarations expands to gigabytes (a
CPU/memory DoS), and a ``SYSTEM`` entity can exfiltrate local files / hit the
network (XXE).

eCTD backbones and STFs legitimately carry a ``<!DOCTYPE ... SYSTEM "util/…dtd">``
that references an *external* DTD by name but NEVER declare internal entities, so
we neutralise both attack classes by refusing any ``<!ENTITY>`` declaration and
never resolving an external entity, while leaving every well-formed, entity-free
document (including the real eCTD index/STF) parsing exactly as before.

This is the single, canonical implementation; ``validation.py`` re-exports it for
backward compatibility and ``ectd``/``stf`` import it directly so there is no
parser that bypasses the hardening.
"""

from __future__ import annotations

from xml.dom.minidom import parseString
from xml.parsers.expat import ParserCreate


class UnsafeXmlError(ValueError):
    """Raised when XML carries a DTD entity declaration or external entity
    reference — the building blocks of billion-laughs / XXE attacks."""


def assert_xml_entity_safe(xml_text) -> None:
    """Reject entity-expansion (billion laughs) and external-entity (XXE) XML.

    Runs a fast, non-expanding expat pass that fires on the *declaration* of any
    entity (before it could ever be expanded) and on any external-entity
    reference, so a hostile payload is refused before it can do work. Raises
    :class:`UnsafeXmlError`; lets a genuinely malformed document fall through to
    the caller's own well-formedness handling.
    """
    parser = ParserCreate()
    # Never parse external parameter entities (closes the XXE vector outright).
    parser.SetParamEntityParsing(0)  # XML_PARAM_ENTITY_PARSING_NEVER

    def _reject_entity_decl(*_args):
        raise UnsafeXmlError("XML entity declarations are not permitted")

    def _reject_external_ref(*_args):
        raise UnsafeXmlError("external XML entities are not permitted")

    parser.EntityDeclHandler = _reject_entity_decl
    parser.ExternalEntityRefHandler = _reject_external_ref
    data = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    try:
        parser.Parse(data, True)
    except UnsafeXmlError:
        raise
    except Exception:
        # Malformed XML that is not an entity attack — defer to the caller, which
        # parses it again and surfaces its own "not well-formed" diagnostic.
        return


def safe_parse_xml(xml_text):
    """Parse caller-supplied XML into a minidom DOM, hardened against
    entity-expansion and external-entity attacks. Use this for any XML that did
    not originate inside the portal."""
    assert_xml_entity_safe(xml_text)
    return parseString(xml_text)
