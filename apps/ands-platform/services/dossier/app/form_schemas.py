"""Declarative form schemas for EVERY authorable eCTD content section (pure).

The vision: every eCTD section should offer FORM-FILL + per-field AI-DRAFT +
GENERATE — not just upload. Today only the six special-format documents
(cover letter, REP application form, Form V, ANDS attestation, QOS scaffold,
CS-BE) can be authored in-app. This module makes the *rest* of the section
tree authorable too, by describing each section's document as a declarative
FORM the web can render uniformly and the universal ``structured`` generator
(see :mod:`generators`) can render into a clean PDF/A-1b-clean PDF.

SHARED FORM-SCHEMA CONTRACT (do not deviate):

  schema = { section, title, description, generator, fields: Field[] }
  Field  = { name, label, type, required, prose, help, options?,
             placeholder?, sample?, bilingual? }

  * type   : "text" | "textarea" | "date" | "select" | "email" | "number"
  * prose  : True  -> AI-draftable free text (per-field AI draft applies)
  * help   : an HC-grounded one-liner telling the filer what HC expects here
  * generator: "structured" (universal PDF from the filled fields) OR a
    bespoke key ("cover_letter", "rep_application_form", "patent_form_v",
    "ands_attestation", "qos_ce_scaffold", "cs_be", "pm_xml") for a special
    format.

Honesty: the fields are the *real* elements HC expects for that document,
grounded in HC guidance — never filler. Generated documents are DRAFTS (they
carry the ``_DRAFT`` watermark) and are never claimed to be HC-accepted.

Pure, stdlib-only, keyed by the section tree's section number.
"""

from __future__ import annotations


# --- Field/schema authoring helpers ----------------------------------------

def _field(name: str, label: str, *, type: str = "text", required: bool = False,
           prose: bool = False, help: str = "", options=None,
           placeholder: str = "", sample: str = "",
           bilingual: bool = False) -> dict:
    """Build one Field per the CONTRACT. ``options`` only for a select."""
    f = {
        "name": name,
        "label": label,
        "type": type,
        "required": bool(required),
        "prose": bool(prose),
        "help": help,
    }
    if type == "select":
        f["options"] = list(options or [])
    if placeholder:
        f["placeholder"] = placeholder
    if sample:
        f["sample"] = sample
    if bilingual:
        f["bilingual"] = True
    return f


def _schema(section: str, title: str, description: str, generator: str,
            fields: list) -> dict:
    return {
        "section": section,
        "title": title,
        "description": description,
        "generator": generator,
        "fields": list(fields),
    }


# Fields common to almost every document — who the sponsor/product are. These
# are pre-filled from the dossier context (form_samples._base) so the filer
# rarely retypes them, but the schema still declares them for a uniform UI.
def _identity_fields() -> list:
    return [
        _field("drug_product", "Drug product", required=True,
               help="The proposed brand name and strength/dosage form of the "
                    "generic (e.g. 'Drugazole 10 mg tablet')."),
        _field("dossier_id", "Dossier ID",
               help="Health Canada dossier identifier for this submission."),
    ]


# ---------------------------------------------------------------------------
# Bespoke-generator sections (already have a special-format generator). We
# register a uniform form schema so the web form UI is identical everywhere;
# ``generator`` points at the existing bespoke key, NOT "structured".
# ---------------------------------------------------------------------------

def _cover_letter() -> dict:
    return _schema(
        "1.0", "Cover Letter",
        "The submission's cover letter — who you are, what you're filing, and "
        "the dossier it belongs to.",
        "cover_letter", [
            _field("sponsor", "Sponsor (company)", required=True,
                   help="The sponsor's legal company name — never the product "
                        "name."),
            _field("company_id", "Company ID",
                   help="Health Canada Company ID so the transaction routes to "
                        "your company file."),
            _field("dossier_id", "Dossier ID",
                   help="Health Canada dossier identifier for this submission."),
            _field("drug_product", "Drug product", required=True,
                   help="Proposed brand name + strength/dosage form."),
            _field("activity_type", "Activity type", type="select",
                   options=["ANDS", "SANDS", "NDS", "SNDS", "DIN"],
                   help="The regulatory activity type for this transaction."),
            _field("sequence", "Sequence", placeholder="0000",
                   help="The four-digit eCTD sequence number (0000 for the "
                        "original)."),
            _field("contact_name", "Regulatory contact",
                   help="Name/title of the regulatory-affairs contact."),
            _field("contact_email", "Contact email", type="email",
                   help="Email of the regulatory contact for this submission."),
            _field("sequence_description", "Purpose / sequence description",
                   type="textarea", prose=True,
                   help="One line describing the purpose of this transaction "
                        "(e.g. 'Original ANDS submission')."),
        ])


def _rep_application_form() -> dict:
    return _schema(
        "1.2.1", "Drug Submission Application Form (REP)",
        "The Regulatory Enrolment Process (REP) CO/RT/PI backbone — the "
        "application form since Oct 2020.",
        "rep_application_form", [
            _field("company_id", "Company ID",
                   help="The sponsor's HC Company ID (COMPANY_ID) — not the "
                        "product."),
            _field("sponsor", "Company name", required=True,
                   help="The sponsor's legal company name (COMPANY_NAME)."),
            _field("dossier_id", "Dossier ID",
                   help="The dossier identifier (DOSSIER_ID)."),
            _field("dossier_type", "Dossier type", type="select",
                   options=["ANDS", "NDS", "SANDS", "SNDS", "DIN"],
                   help="The dossier type."),
            _field("activity_type", "Activity type", type="select",
                   options=["ANDS", "NDS", "SANDS", "SNDS", "DIN"],
                   help="The regulatory activity type."),
            _field("sequence", "Sequence number", placeholder="0000",
                   help="The eCTD sequence number."),
            _field("sequence_description", "Sequence description",
                   help="A short description of this sequence."),
            _field("drug_product", "Product name", required=True,
                   help="The proposed product name (PRODUCT_NAME)."),
            _field("din", "DIN",
                   help="Drug Identification Number — empty until HC assigns "
                        "it at NOC."),
        ])


def _patent_form_v() -> dict:
    return _schema(
        "1.2.4", "Intellectual Property — Form V Declaration (PM(NOC))",
        "The generic's section-5 declaration addressing patents/CSPs on the "
        "Patent Register for the Canadian Reference Product.",
        "patent_form_v", [
            _field("drug_product", "Drug product", required=True,
                   help="The proposed generic product."),
            _field("crp_brand", "Canadian Reference Product", required=True,
                   help="The brand name of the Canadian Reference Product."),
            _field("crp_din", "Reference DIN",
                   help="The DIN of the Canadian Reference Product."),
            _field("patents", "Patent/CSP number(s)",
                   help="Each patent/CSP listed on the Register for the CRP "
                        "(leave blank if the Register lists none)."),
            _field("patent_expiry", "Patent/CSP expiry", type="date",
                   help="Expiry date per listed patent/CSP."),
            _field("allegation", "Section-5 statement", type="textarea",
                   prose=True,
                   help="ONE s.5 statement per patent: not addressed / accepts "
                        "expiry / alleges invalidity / alleges "
                        "non-infringement. An invalidity/non-infringement "
                        "allegation also requires serving a Notice of "
                        "Allegation (NOA)."),
        ])


def _ands_attestation() -> dict:
    return _schema(
        "1.2.3", "ANDS Sponsor Attestation",
        "The sponsor's signed attestation that the ANDS is accurate, complete "
        "and not misleading.",
        "ands_attestation", [
            _field("drug_product", "Drug product", required=True,
                   help="The proposed generic product."),
            _field("dossier_id", "Dossier ID",
                   help="Health Canada dossier identifier."),
            _field("signer", "Authorized signer",
                   help="The person attesting on behalf of the sponsor."),
            _field("signer_title", "Signer title",
                   help="The signer's title/role."),
        ])


def _qos_ce_scaffold() -> dict:
    return _schema(
        "2.3", "Quality Overall Summary — QOS-CE(BE)",
        "The quality summary of Module 3 — the QOS-CE(BE) bioequivalence "
        "variant for an ANDS.",
        "qos_ce_scaffold", [
            _field("drug_product", "Drug product", required=True,
                   help="The proposed generic product."),
            _field("manufacturer", "Manufacturer",
                   help="The drug-product manufacturer."),
            _field("shelf_life", "Shelf life",
                   help="Proposed shelf life (e.g. '24 months')."),
            _field("storage", "Storage statement",
                   help="Storage conditions (e.g. 'Store at 15-30 C')."),
            _field("s_summary", "Drug substance summary (2.3.S)",
                   type="textarea", prose=True,
                   help="Summarise the Module 3 drug-substance data "
                        "(general information, manufacture, characterisation, "
                        "control, reference standards, container closure, "
                        "stability)."),
            _field("p_summary", "Drug product summary (2.3.P)",
                   type="textarea", prose=True,
                   help="Summarise the Module 3 drug-product data "
                        "(description/composition, development, manufacture, "
                        "excipients, control, reference standards, container "
                        "closure, stability)."),
        ])


def _cs_be() -> dict:
    return _schema(
        "1.6", "Comprehensive Summary — Bioequivalence (CS-BE)",
        "The Canadian comparative-bioavailability (bioequivalence) summary "
        "supporting the ANDS.",
        "cs_be", [
            _field("drug_product", "Test product", required=True,
                   help="The proposed generic (test) product."),
            _field("crp_brand", "Canadian Reference Product", required=True,
                   help="The brand name of the Canadian Reference Product."),
            _field("crp_din", "Reference DIN",
                   help="The DIN of the Canadian Reference Product."),
            _field("dosage_form", "Dosage form",
                   help="The dosage form (e.g. 'immediate-release tablet')."),
            _field("strength", "Strength",
                   help="The strength (e.g. '10 mg')."),
            _field("study_design", "Study design",
                   help="e.g. 'single-dose, fasting, randomized, two-way "
                        "crossover'."),
            _field("auc_ci", "AUC 90% CI",
                   help="The AUC 90% confidence interval (limits 80.00-125.00%)."),
            _field("cmax", "Cmax 90% CI / PE",
                   help="The Cmax 90% CI and point estimate."),
            _field("ruleset", "Ruleset",
                   help="The BE ruleset applied (ICH M13A or legacy)."),
            _field("conclusion", "Bioequivalence conclusion", type="textarea",
                   prose=True,
                   help="State clearly whether the test product is "
                        "bioequivalent to the reference on AUC and Cmax."),
        ])


# ---------------------------------------------------------------------------
# Universal "structured" sections — currently upload-only. Each declares the
# real HC-expected fields; the universal generator renders them to a clean PDF.
# ---------------------------------------------------------------------------

def _authorization_correspondence() -> dict:
    return _schema(
        "1.2.5", "Authorization & Regulatory Correspondence",
        "Sponsor/technical/quality contacts and any authorization letters.",
        "structured", [
            _field("sponsor", "Sponsor (company)",
                   help="The sponsor's legal company name."),
            _field("regulatory_contact", "Regulatory contact",
                   help="Name/title of the primary regulatory-affairs contact."),
            _field("regulatory_email", "Regulatory contact email",
                   type="email",
                   help="Email of the primary regulatory contact."),
            _field("quality_contact", "Quality/technical contact",
                   help="Name/title of the quality or technical contact."),
            _field("safety_contact", "Safety/pharmacovigilance contact",
                   help="Name/title of the safety/PV contact, if applicable."),
            _field("authorization", "Authorization statement", type="textarea",
                   prose=True,
                   help="Any letter of authorization — e.g. authorising an "
                        "agent to correspond with HC on the sponsor's behalf."),
        ])


def _lasa() -> dict:
    return _schema(
        "1.3.2", "Look-alike Sound-alike (LASA) Brand-name Assessment",
        "The look-alike / sound-alike safety assessment of the proposed brand "
        "name.",
        "structured", [
            _field("proposed_name", "Proposed brand name", required=True,
                   help="The brand name being assessed for LASA confusion."),
            _field("similar_names", "Similar existing names",
                   help="Marketed names that look or sound alike."),
            _field("methodology", "Assessment methodology", type="textarea",
                   prose=True,
                   help="How the name was screened (orthographic/phonetic "
                        "analysis, POCA-style search, prescriber testing)."),
            _field("risk_conclusion", "Risk conclusion", type="textarea",
                   prose=True,
                   help="The confusion-risk conclusion and any mitigations."),
        ])


def _labelling() -> dict:
    return _schema(
        "1.3.3", "Labelling",
        "Bilingual mock-ups: inner label, outer label, package, and package "
        "insert.",
        "structured", [
            _field("inner_label", "Inner label text", type="textarea",
                   prose=True, bilingual=True,
                   help="Inner-label copy (EN + FR); min. 10 pt sans-serif."),
            _field("outer_label", "Outer label text", type="textarea",
                   prose=True, bilingual=True,
                   help="Outer-label copy (EN + FR)."),
            _field("package_insert", "Package insert", type="textarea",
                   prose=True, bilingual=True,
                   help="Package-insert copy (EN + FR)."),
            _field("net_quantity", "Net quantity / fill",
                   help="Net quantity declared on the label."),
        ])


def _hc_summaries() -> dict:
    return _schema(
        "1.4", "Health Canada Summaries",
        "Health-Canada-specific summaries (e.g. a multidisciplinary tabular "
        "summary) — generally optional for a straightforward ANDS.",
        "structured", [
            _field("summary_type", "Summary type",
                   help="The kind of HC summary provided."),
            _field("summary", "Summary", type="textarea", prose=True,
                   help="The HC-specific summary content."),
        ])


def _environmental() -> dict:
    return _schema(
        "1.5", "Environmental Assessment Statement",
        "Environmental impact assessment, where required by the product class.",
        "structured", [
            _field("applicable", "Applicable?", type="select",
                   options=["Yes", "No"],
                   help="Whether an environmental assessment applies to this "
                        "product class."),
            _field("statement", "Environmental statement", type="textarea",
                   prose=True,
                   help="The environmental impact assessment, or the "
                        "justification that none is required."),
        ])


def _m2_introduction() -> dict:
    return _schema(
        "2.2", "Introduction",
        "A brief overview of the drug: pharmacological class, mode of action, "
        "and proposed use.",
        "structured", [
            _field("drug_product", "Drug product", required=True,
                   help="The proposed generic product."),
            _field("pharmacological_class", "Pharmacological class",
                   help="The pharmacological/therapeutic class."),
            _field("introduction", "Introduction", type="textarea", prose=True,
                   help="A short introduction: class, mode of action, and the "
                        "proposed indication/use."),
        ])


# The ICH CTD Module-2 overviews/summaries (2.4-2.7) — suppressed on the
# CS-BE path but authorable when present. All share a class + prose shape.
def _m2_overview(section: str, title: str, help: str) -> dict:
    return _schema(
        section, title,
        f"{title} — the CTD Module-2 summary.",
        "structured", [
            _field("drug_product", "Drug product",
                   help="The proposed generic product."),
            _field("summary", title, type="textarea", prose=True, help=help),
        ])


# --- Module 3 (Quality / CMC) drug-substance & drug-product subsections -----
def _cmc(section: str, title: str, help: str,
         extra: list | None = None) -> dict:
    fields = [
        _field("drug_product", "Drug product",
               help="The proposed generic product."),
    ] + list(extra or []) + [
        _field("content", title, type="textarea", prose=True, help=help),
    ]
    return _schema(section, title,
                   f"{title} — Module 3 quality (CMC).", "structured", fields)


# ---------------------------------------------------------------------------
# Module-5 clinical study report metadata (the report itself is uploaded, but
# the section is authorable as a structured cover/description).
# ---------------------------------------------------------------------------
def _product_monograph() -> dict:
    """Stub schema for 1.3.1 — the full XML Product Monograph builder is
    workstream 2 (:mod:`pm_xml`, generator ``pm_xml``). This declares the
    top-level bilingual PM fields so the form UI is uniform; the bespoke
    ``pm_xml`` generator (not ``structured``) owns the real rendering.
    """
    return _schema(
        "1.3.1", "Product Monograph (bilingual, incl. PMI)",
        "The Product Monograph in English AND French, following the HC Master "
        "Template. The Patient Medication Information (Part III) sits inside.",
        "pm_xml", [
            _field("drug_product", "Drug product", required=True, bilingual=True,
                   help="Proposed brand name + strength/dosage form."),
            _field("indications", "Indications", type="textarea", prose=True,
                   bilingual=True,
                   help="The approved indication(s) (EN + FR)."),
            _field("dosage", "Dosage & administration", type="textarea",
                   prose=True, bilingual=True,
                   help="Recommended dose and administration (EN + FR)."),
            _field("patient_information", "Patient Medication Information",
                   type="textarea", prose=True, bilingual=True,
                   help="Part III plain-language PMI, Grade 6-8 reading level "
                        "(EN + FR)."),
        ])


def _cs_531() -> dict:
    return _schema(
        "5.3.1", "Comparative Bioavailability / Bioequivalence Study Reports",
        "The pivotal comparative BA/BE study report(s) — the core evidence "
        "for an ANDS.",
        "structured", [
            _field("study_title", "Study title", required=True,
                   help="Title of the pivotal comparative BA/BE study."),
            _field("study_number", "Study number",
                   help="The sponsor's protocol/study number."),
            _field("crp_brand", "Canadian Reference Product",
                   help="The Canadian Reference Product used as comparator."),
            _field("study_design", "Study design",
                   help="e.g. 'single-dose, fasting, two-way crossover'."),
            _field("results_summary", "Results summary", type="textarea",
                   prose=True,
                   help="Summarise the AUC/Cmax 90% CI against 80-125% and the "
                        "bioequivalence conclusion; the full report is "
                        "uploaded alongside."),
        ])


# ---------------------------------------------------------------------------
# The registry: section number -> schema builder. One entry per authorable
# CONTENT (document) section in the tree. Group nodes and the auto-backbone
# (1.1 / 2.1) have NO schema.
# ---------------------------------------------------------------------------
_BUILDERS = {
    # bespoke-generator sections
    "1.0": _cover_letter,
    "1.2.1": _rep_application_form,
    "1.2.3": _ands_attestation,
    "1.2.4": _patent_form_v,
    "1.6": _cs_be,
    "2.3": _qos_ce_scaffold,
    # Product Monograph 1.3.1 — bespoke pm_xml generator (workstream 2)
    "1.3.1": _product_monograph,
    # universal structured sections (were upload-only)
    "1.2.5": _authorization_correspondence,
    "1.3.2": _lasa,
    "1.3.3": _labelling,
    "1.4": _hc_summaries,
    "1.5": _environmental,
    "2.2": _m2_introduction,
    "2.4": lambda: _m2_overview(
        "2.4", "Nonclinical Overview",
        "Overview of nonclinical (animal) pharmacology/toxicology."),
    "2.5": lambda: _m2_overview(
        "2.5", "Clinical Overview",
        "Overview of clinical efficacy and safety."),
    "2.6": lambda: _m2_overview(
        "2.6", "Nonclinical Written & Tabulated Summaries",
        "Detailed nonclinical written and tabulated summaries."),
    "2.7": lambda: _m2_overview(
        "2.7", "Clinical Summary",
        "Detailed clinical summary."),
    # Module 3 — drug substance 3.2.S.1-.7
    "3.2.S.1": lambda: _cmc(
        "3.2.S.1", "General Information (Nomenclature, Structure, Properties)",
        "Name, structure and physicochemical properties of the drug "
        "substance."),
    "3.2.S.2": lambda: _cmc(
        "3.2.S.2", "Manufacture",
        "Manufacturer(s) and manufacturing process of the drug substance; may "
        "reference acceptable innovator/DMF data."),
    "3.2.S.3": lambda: _cmc(
        "3.2.S.3", "Characterisation",
        "Elucidation of structure and the impurity profile."),
    "3.2.S.4": lambda: _cmc(
        "3.2.S.4", "Control of Drug Substance",
        "Specifications, analytical procedures and batch analyses — at least "
        "as stringent as the reference product."),
    "3.2.S.5": lambda: _cmc(
        "3.2.S.5", "Reference Standards or Materials",
        "The reference standards or materials used in testing."),
    "3.2.S.6": lambda: _cmc(
        "3.2.S.6", "Container Closure System",
        "The drug-substance container closure system."),
    "3.2.S.7": lambda: _cmc(
        "3.2.S.7", "Stability",
        "Accelerated and long-term stability data for the drug substance."),
    # Module 3 — drug product 3.2.P.1-.8
    "3.2.P.1": lambda: _cmc(
        "3.2.P.1", "Description & Composition",
        "Description and composition establishing pharmaceutical equivalence "
        "to the reference."),
    "3.2.P.2": lambda: _cmc(
        "3.2.P.2", "Pharmaceutical Development",
        "Development of the formulation; biowaiver justification per ICH M9 "
        "if applicable."),
    "3.2.P.3": lambda: _cmc(
        "3.2.P.3", "Manufacture",
        "Manufacturer(s), the manufacturing process and its controls."),
    "3.2.P.4": lambda: _cmc(
        "3.2.P.4", "Control of Excipients",
        "Specifications and testing of the excipients."),
    "3.2.P.5": lambda: _cmc(
        "3.2.P.5", "Control of Drug Product",
        "Specifications, analytical procedures and batch analyses — matching "
        "or exceeding the reference product."),
    "3.2.P.6": lambda: _cmc(
        "3.2.P.6", "Reference Standards or Materials",
        "The reference standards or materials for the drug product."),
    "3.2.P.7": lambda: _cmc(
        "3.2.P.7", "Container Closure System",
        "Description and suitability of the drug-product packaging."),
    "3.2.P.8": lambda: _cmc(
        "3.2.P.8", "Stability",
        "Accelerated and long-term stability; >=3 batches; conditions "
        "matching the approved reference."),
    # Module 3 — regional + literature
    "3.2.R": lambda: _cmc(
        "3.2.R", "Regional Information",
        "Canada-specific quality information (e.g. a device component)."),
    "3.3": lambda: _cmc(
        "3.3", "Literature References",
        "Supporting quality literature references."),
    # Module 5
    "5.3.1": _cs_531,
}

# The bespoke (special-format) generators — their schema's ``generator`` is the
# bespoke key, not "structured". Everything else routes through "structured".
BESPOKE_GENERATORS = {
    "1.0": "cover_letter",
    "1.2.1": "rep_application_form",
    "1.2.3": "ands_attestation",
    "1.2.4": "patent_form_v",
    "1.6": "cs_be",
    "2.3": "qos_ce_scaffold",
}


def form_schema(section: str) -> dict | None:
    """The declarative form schema for a content section, or None if the
    section has no authorable form (group nodes, the auto-backbone)."""
    builder = _BUILDERS.get(str(section or "").strip())
    return builder() if builder else None


def registry() -> dict:
    """All form schemas, keyed by section number."""
    return {section: builder() for section, builder in _BUILDERS.items()}


def prose_fields(section: str) -> list:
    """The names of the AI-draftable (prose) fields in a section's schema."""
    schema = form_schema(section)
    if not schema:
        return []
    return [f["name"] for f in schema["fields"] if f.get("prose")]


def field_for(section: str, field_name: str) -> dict | None:
    """One field descriptor from a section's schema (or None)."""
    schema = form_schema(section)
    if not schema:
        return None
    name = str(field_name or "").strip()
    return next((f for f in schema["fields"] if f["name"] == name), None)
