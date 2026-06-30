"""Pydantic request models for the dossier API (business rules live in domain)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContentPlanIn(BaseModel):
    dossier_id: str = ""
    submission_type: str = ""
    cs_be_only: bool = False


class ItemAssignIn(BaseModel):
    id: str
    assignee: str = ""
    due_date: str | None = None


class ItemStatusIn(BaseModel):
    id: str
    status: str = ""


class PmLeafIn(BaseModel):
    dossier_id: str = ""
    lang: str = ""
    title: str = ""
    version: int = 1
    leaf_id: str | None = None


class AdminSequenceIn(BaseModel):
    dossier_id: str = ""
    activity: str = ""
    sequence: str = ""
    operations: list[dict] = Field(default_factory=list)
    present_documents: list[dict] = Field(default_factory=list)
    cover_letter_generated: bool = True


class PmXmlBuildIn(BaseModel):
    dossier_id: str = ""
    lang: str = "en"
    product_name: str = ""
    din: str = ""
    sections: list[dict] = Field(default_factory=list)
    images: list[dict] = Field(default_factory=list)


class PmXmlValidateIn(BaseModel):
    xml: str = ""


class PmXmlGateIn(BaseModel):
    xml_pm_required: bool = False
    has_xml_pm: bool = False
    has_pdf_pm: bool = False


class PmXrefIn(BaseModel):
    sections: list[dict] = Field(default_factory=list)
    refs: list = Field(default_factory=list)
    xrefs: list[dict] = Field(default_factory=list)
    present_targets: list[str] | None = None


class LeafIn(BaseModel):
    dossier_id: str = ""
    sequence: str = "0000"
    leaf_id: str = ""
    operation: str = "new"
    heading: str = ""
    title: str = ""
    href: str = ""
    modified_leaf: str = ""
    content: str = ""


class BinderIn(BaseModel):
    dossier_id: str = ""
    sequence: str = "0000"
    validation_report: dict | None = None
    transmission: dict | None = None
