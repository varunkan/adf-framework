"""
ANDS Submission Portal — version-pluggable backbone generator (REQ-041).

The eCTD "backbone" (index.xml / ca-regional.xml today, an HL7-RPS message
tomorrow) is produced from a *neutral content model* through a pluggable
generator interface. The SAME content model can therefore emit the ICH+CA
eCTD v3.2.2 backbone today and the HL7-RPS eCTD v4.0 message when HC adopts it,
with NO re-authoring of content.

Persistent document UUIDs are assigned now (deterministically, via uuid5 over a
stable document key) so a document keeps the same identity across sequences and
applications — which is exactly what the v4.0 message requires.

Pure Python 3 standard library. Deterministic and unit-testable.

REQ-041 caveat encoded in data, not prose: the v4.0 adoption dates are
industry-roadmap ESTIMATES (the HC draft CA Module 1 TIG went to consultation
in June 2019 and its original timeline lapsed); they are NOT HC-fixed
commitments and must never be presented as such.
"""

from __future__ import annotations

import uuid

import ectd

# A fixed namespace so UUID assignment is deterministic and reproducible across
# runs/processes — a document's identity is a pure function of its key.
UUID_NAMESPACE = uuid.UUID("a4f0d3c2-0b1e-5e7a-9c3d-2f1b6a8e4c50")

# Backbone format families this interface can emit.
FORMAT_ECTD_322 = "eCTD-3.2.2"
FORMAT_RPS_40 = "HL7-RPS-4.0"


# ---------------------------------------------------------------------------
# Persistent document UUIDs (REQ-041)
# ---------------------------------------------------------------------------

def document_key(dossier_id: str, document_id: str) -> str:
    """Stable identity key for a document, independent of sequence.

    A document keeps ONE identity for the life of the application; the same
    (dossier, document) always maps to the same key (and hence the same UUID),
    no matter which sequence ships it.
    """
    return f"{str(dossier_id or '').strip()}::{str(document_id or '').strip()}"


def assign_document_uuid(dossier_id: str, document_id: str) -> str:
    """REQ-041: assign a persistent document UUID, retained across sequences
    and applications. Deterministic (uuid5) so the SAME document always
    resolves to the SAME UUID — no central registry required to keep identity.
    """
    return str(uuid.uuid5(UUID_NAMESPACE, document_key(dossier_id, document_id)))


# ---------------------------------------------------------------------------
# Neutral content model (REQ-041)
# ---------------------------------------------------------------------------

class ContentModel:
    """Format-neutral dossier content: the single source a generator emits from.

    A document carries its persistent UUID, a heading (Context-of-Use anchor),
    an href, an operation/lifecycle and a checksum — everything both the v3.2.2
    backbone and the v4.0 message need, with nothing format-specific baked in.
    """

    def __init__(self, dossier_id: str, sequence: str, documents=None):
        self.dossier_id = str(dossier_id or "").strip()
        self.sequence = str(sequence or "").strip()
        self.documents = list(documents or [])

    def add_document(self, document_id: str, heading: str, href: str,
                     content: str = "", operation: str = "new",
                     modified_leaf: str = "", title: str = "") -> dict:
        """Add a document, assigning (and retaining) its persistent UUID."""
        doc = {
            "document_id": str(document_id or "").strip(),
            "uuid": assign_document_uuid(self.dossier_id, document_id),
            "heading": str(heading or "").strip(),
            "href": str(href or "").strip(),
            "content": content if content is not None else "",
            "operation": str(operation or "new").strip(),
            "modified_leaf": str(modified_leaf or "").strip(),
            "title": str(title or document_id or "").strip(),
        }
        self.documents.append(doc)
        return doc

    def to_leaves(self) -> list:
        """Project the content model onto the eCTD leaf shape ectd.* expects."""
        leaves = []
        for d in self.documents:
            leaves.append({
                "leaf_id": d["document_id"],
                "uuid": d["uuid"],
                "heading": d["heading"],
                "href": d["href"],
                "operation": d["operation"],
                "modified_leaf": d["modified_leaf"],
                "title": d["title"],
                "checksum": ectd.md5_hex(d.get("content") or ""),
            })
        return leaves

    def to_dict(self) -> dict:
        return {
            "dossier_id": self.dossier_id,
            "sequence": self.sequence,
            "documents": self.documents,
        }

    @classmethod
    def from_request(cls, data: dict) -> "ContentModel":
        cm = cls(data.get("dossier_id", ""), data.get("sequence", ""))
        for d in (data.get("documents") or []):
            cm.add_document(
                document_id=d.get("document_id", ""),
                heading=d.get("heading", ""),
                href=d.get("href", ""),
                content=d.get("content", ""),
                operation=d.get("operation", "new"),
                modified_leaf=d.get("modified_leaf", ""),
                title=d.get("title", ""),
            )
        return cm


# ---------------------------------------------------------------------------
# Generator interface + implementations (REQ-041)
# ---------------------------------------------------------------------------

class BackboneGenerator:
    """The pluggable interface. A new target version = a new subclass; the
    content model and calling code do NOT change."""

    version = ""
    format = ""
    fixed_by_hc = True       # is the version a binding HC commitment?
    adopted = True           # is it adoptable today?

    def emit(self, model: ContentModel) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError


class EctdV322Generator(BackboneGenerator):
    """Today's target: the ICH eCTD v3.2.2 + CA Module 1 regional backbone.

    Emitted through the existing, validated ectd.* builders — the content model
    is the only new surface."""

    version = "3.2.2"
    format = FORMAT_ECTD_322
    fixed_by_hc = True
    adopted = True

    def emit(self, model: ContentModel) -> dict:
        leaves = model.to_leaves()
        index_xml = ectd.build_index_xml(
            model.dossier_id, model.sequence, leaves)
        ca_xml = ectd.build_ca_regional_xml(
            model.dossier_id, model.sequence, leaves)
        # Validate through the pinned schema/DTD descriptors (mirrors A06a).
        ectd.validate_backbone(index_xml, ectd.ICH_ECTD_DTD)
        ectd.validate_backbone(ca_xml, ectd.CA_M1_XSD)
        return {
            "version": self.version,
            "format": self.format,
            "artifacts": {
                "index.xml": index_xml,
                "ca-regional.xml": ca_xml,
            },
            "document_uuids": {d["document_id"]: d["uuid"]
                               for d in model.documents},
        }


class RpsV40Generator(BackboneGenerator):
    """Tomorrow's target: the HL7-RPS eCTD v4.0 message.

    Emits a v4.0 submissionUnit message from the SAME content model — persistent
    document UUIDs become the priorityNumber/document identity, headings become
    Context-of-Use codes, controlled vocabularies are Genericode-referenced, and
    the message advertises two-way (controlled correspondence) messaging.

    NOTE: v4.0 is NOT yet HC-fixed (``fixed_by_hc = False``); selecting it is for
    forward-compatibility validation, never a claim that HC mandates it.
    """

    version = "4.0"
    format = FORMAT_RPS_40
    fixed_by_hc = False
    adopted = False

    def emit(self, model: ContentModel) -> dict:
        from xml.sax.saxutils import escape as esc

        cou = []
        for d in model.documents:
            cou.append(
                '    <contextOfUse classCode="ACT" moodCode="EVN">\n'
                f'      <id root="{esc(d["uuid"])}"/>\n'
                f'      <code code="{esc(d["heading"])}" '
                'codeSystem="2.16.840.1.113883.3.989.2.2.1.1.1" '
                'codeSystemName="Genericode:ich-heading"/>\n'
                '      <derivedFrom>\n'
                '        <documentReference>\n'
                f'          <id root="{esc(d["uuid"])}"/>\n'
                '        </documentReference>\n'
                '      </derivedFrom>\n'
                '    </contextOfUse>\n'
            )
        message = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<submissionUnit xmlns="urn:hl7-org:v3" '
            'ITSVersion="XML_1.0">\n'
            f'  <id root="{esc(model.dossier_id)}" '
            f'extension="{esc(model.sequence)}"/>\n'
            '  <code code="submissionUnit" '
            'codeSystem="2.16.840.1.113883.3.989.2.2.1.1.6" '
            'codeSystemName="Genericode:submission-unit-type"/>\n'
            '  <twoWayMessaging value="true"/>\n'
            '  <contextOfUseList>\n'
            f'{"".join(cou)}'
            '  </contextOfUseList>\n'
            '</submissionUnit>\n'
        )
        return {
            "version": self.version,
            "format": self.format,
            "artifacts": {"rps-message.xml": message},
            "document_uuids": {d["document_id"]: d["uuid"]
                               for d in model.documents},
        }


# Registry — adding a version is data, not a rewrite (REQ-041 / REQ-040).
GENERATORS = {
    "3.2.2": EctdV322Generator,
    "4.0": RpsV40Generator,
}

# The default/active target: only an adopted, HC-fixed version may be active.
ACTIVE_BACKBONE_VERSION = "3.2.2"


class UnknownBackboneVersionError(ValueError):
    """REQ-041: a backbone version with no registered generator was selected."""


def get_generator(version: str = ACTIVE_BACKBONE_VERSION) -> BackboneGenerator:
    version = str(version or "").strip() or ACTIVE_BACKBONE_VERSION
    cls = GENERATORS.get(version)
    if cls is None:
        raise UnknownBackboneVersionError(
            f"no backbone generator registered for version '{version}'; "
            f"known versions: {', '.join(sorted(GENERATORS))}")
    return cls()


def list_backbone_versions() -> list:
    """Every registered target with its adoption status (estimates flagged)."""
    out = []
    for ver in sorted(GENERATORS):
        g = GENERATORS[ver]()
        out.append({
            "version": g.version,
            "format": g.format,
            "fixed_by_hc": g.fixed_by_hc,
            "adopted": g.adopted,
            "active": ver == ACTIVE_BACKBONE_VERSION,
        })
    return out


# v4.0 adoption roadmap — ESTIMATES, explicitly not HC-fixed (REQ-041).
ADOPTION_ROADMAP = {
    "format": FORMAT_RPS_40,
    "source": "industry roadmap (ICH/RPS); HC draft CA Module 1 TIG "
              "consultation June 2019",
    "estimate": True,
    "hc_fixed": False,
    "note": "v4.0 adoption dates are industry-roadmap estimates; the original "
            "HC draft timeline has lapsed. No binding HC notice as of 2026-06. "
            "Do not present these as HC-fixed commitments.",
    "milestones": [
        {"phase": "voluntary", "target": "TBD", "estimate": True,
         "hc_fixed": False},
        {"phase": "mandatory", "target": "TBD", "estimate": True,
         "hc_fixed": False},
    ],
}


def generate_backbone(data: dict) -> dict:
    """REQ-041 service entry: build a content model from a request and emit it
    through the selected (default active) generator."""
    version = str(data.get("version", "") or "").strip() or ACTIVE_BACKBONE_VERSION
    model = ContentModel.from_request(data)
    generator = get_generator(version)
    result = generator.emit(model)
    result["content_model"] = model.to_dict()
    return result
