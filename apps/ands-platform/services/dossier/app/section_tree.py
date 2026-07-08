"""The full versioned Health Canada eCTD section tree for an ANDS (M1–M5).

Extends the 6-heading Module-1 placement (:mod:`ectd`) into the COMPLETE per-section
structure a filer must build, with plain-language purpose + guidance, the HC forms,
per-section affordances (``upload`` / ``generate`` / ``mark_na``), a document
``generator_key`` where the portal can author it, format hints, and a canada.ca
citation — so the guided module builder can tell the filer exactly what goes in
each section with zero guessing. Pure, stdlib-only, versioned reference data.

ANDS applicability (required / optional / suppressed / na) follows the same rules
as :mod:`content_model`: an ANDS on the comparative-BE (CS-BE) path suppresses
Modules 2.4–2.7 and never needs Module 4; Modules 1, 2.3, 3 and 5.3.1 are required.
"""

from __future__ import annotations

from . import ectd
from .generators import LLM_DRAFTABLE

SECTION_TREE_VERSION = "2024-04-23"   # HC Module-1 placement + CTD structure

_APPS = ("https://www.canada.ca/en/health-canada/services/drugs-health-products"
         "/drug-products/applications-submissions")
_URL = {
    "m1": f"{_APPS}/guidance-documents/organization-document-placement-canadian-module-1.html",
    "ectd": f"{_APPS}/guidance-documents/ectd/preparation-drug-submissions-electronic-common-technical-document.html",
    "rep": "https://health-products.canada.ca/rep-pir/index.html",
    "forms": f"{_APPS}/forms.html",
    "pm": f"{_APPS}/guidance-documents/product-monograph/master-template.html",
    "pmi": f"{_APPS}/guidance-documents/product-monograph/guidance-document-product-monograph.html",
    "labels": f"{_APPS}/guidance-documents/labelling-pharmaceutical-drugs-humans.html",
    "csbe": f"{_APPS}/templates/notice-draft-comprehensive-summary-bioequivalence.html",
    "qos": f"{_APPS}/templates.html",
    "cmc": f"{_APPS}/guidance-documents/chemical-entity-products-quality/guidance-document-quality-chemistry-manufacturing-guidance-new-drug-submissions-ndss-abbreviated-new-drug-submissions.html",
    "babe": f"{_APPS}/guidance-documents/bioavailability-bioequivalence/conduct-analysis-comparative.html",
    "fees": "https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/fees/fees-review-drug-submissions-applications.html",
    "smallbiz": "https://www.canada.ca/en/health-canada/services/drugs-health-products/funding-fees/small-business-mitigation.html",
}

# Node authoring shorthand:
#   (section, title, kind, applies, affordances, generator_key, formats,
#    bilingual, purpose, guidance, url_key)
# kind: "group" (informational header, no document) | "document"
# applies: "required" | "optional" | "conditional"  (before cs_be/na overlay)
_R, _O, _C = "required", "optional", "conditional"
_UP, _GEN, _NA = "upload", "generate", "mark_na"

# module -> (title, [nodes]). Section numbers follow the HC "Organization and
# document placement for Canadian Module 1" table (1.0/1.2–1.7; 1.2.1 application
# form, 1.2.2 fees, 1.2.3 certification & attestation, 1.2.4 intellectual
# property/patent) and the ICH CTD (Modules 2–5). ``sup`` = CS-BE-suppressed,
# ``na`` = not applicable to a generic ANDS. The Comprehensive ToC (1.1 / 2.1) is
# the eCTD backbone (index.xml / ca-regional.xml), generated automatically — not a
# document to upload.
_MODULES: list[dict] = [
    {"module": "1", "title": "Module 1 — Administrative & regional (Canada)", "nodes": [
        {"s": "1.0", "t": "Cover Letter", "k": "document", "a": _R,
         "aff": [_GEN, _UP], "gen": "cover_letter", "fmt": ["pdf"], "bi": False,
         "p": "Your submission's cover letter — who you are, what you're filing, and the dossier it belongs to.",
         "g": "Health Canada gives you the placement slot; the portal generates the letter from your dossier/company/product details. It names the activity type and sequence and lists your contacts. Generate it here or upload your own.",
         "u": "m1"},
        {"s": "1.1", "t": "Comprehensive Table of Contents", "k": "document", "a": _O,
         "aff": [], "gen": None, "fmt": [], "bi": False,
         "p": "The comprehensive table of contents for the whole submission.",
         "g": "In eCTD this is NOT a document you upload — it IS the eCTD backbone (index.xml + the Canadian ca-regional.xml) generated automatically from the documents you place. View it any time in the Application Viewer.",
         "u": "ectd"},
        {"s": "1.2", "t": "Administrative Information", "k": "group", "a": _R,
         "p": "The regulatory/administrative package — application form, fees, certifications, patents, authorizations.",
         "g": "Everything Health Canada needs to process the submission administratively. Complete each item below.",
         "u": "m1"},
        {"s": "1.2.1", "t": "Drug Submission Application Form", "k": "document",
         "a": _R, "aff": [_GEN, _UP], "gen": "rep_application_form", "fmt": ["xml", "pdf"],
         "bi": False,
         "p": "The application form — since Oct 2020 this is the Regulatory Enrolment Process (REP) template, not the old HC/SC 3011.",
         "g": "Identifies the sponsor (Company ID), the product, the Dossier ID, the regulatory activity type and the sequence. The portal generates the REP CO/RT/PI XML from your single set of identifiers (no re-keying); or upload the completed REP XML.",
         "u": "rep"},
        {"s": "1.2.2", "t": "Fees & Small-business", "k": "document", "a": _R,
         "aff": [_UP], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Fee payment information — and, if you qualify, the small-business status confirmation.",
         "g": "Fees follow the Fees Order (CPI-indexed each April 1) — the portal shows the live current-fiscal-year ANDS review fee. Small-business status (≤300 staff or <$100M revenue incl. affiliates) gives a 50% reduction and a full waiver on your FIRST-ever submission, but status must be GRANTED BEFORE you file. Upload the fee/small-business form.",
         "u": "fees"},
        {"s": "1.2.3", "t": "Certification & Attestation (ANDS Sponsor Attestation)",
         "k": "document", "a": _R, "aff": [_GEN, _UP], "gen": "ands_attestation",
         "fmt": ["pdf"], "bi": False,
         "p": "The sponsor's signed attestation that the ANDS is accurate, complete and not misleading.",
         "g": "Certification & attestation forms live at 1.2.3. The ANDS Sponsor Attestation is required for an ANDS (not for SANDS or labelling-only). Note the ANDS Sponsor Attestation Checklist is requested from Health Canada by email, not on the public forms page. The portal produces the attestation for signature; or upload the signed form.",
         "u": "forms"},
        {"s": "1.2.4", "t": "Intellectual Property — Form V Declaration (PM(NOC))",
         "k": "document", "a": _R, "aff": [_GEN, _UP], "gen": "patent_form_v",
         "fmt": ["pdf"], "bi": False,
         "p": "Address the patents/CSPs on the Patent Register for the Canadian Reference Product.",
         "g": "Intellectual-property information lives at 1.2.4. The generic FILES Form V (Declaration Re: Patent List) under the Patented Medicines (Notice of Compliance) Regulations — per listed patent/CSP on the Register for the Canadian Reference Product: number, expiry, and ONE s.5 statement (not addressed / accepts expiry / alleges invalidity / alleges non-infringement — or that the Register lists no patents). When alleging invalidity or non-infringement, the generic also SERVES a Notice of Allegation (NOA) on the innovator. The portal scaffolds the declaration from your reference-product + patent inputs, or upload a completed Form V.",
         "u": "forms"},
        {"s": "1.2.5", "t": "Authorization & Regulatory Correspondence", "k": "document",
         "a": _O, "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Contact information and authorization letters (sponsor, regulatory, quality contacts).",
         "g": "Sponsor & technical/safety contacts and any authorization letters. Mark N/A if not applicable.",
         "u": "m1"},
        {"s": "1.3", "t": "Product Information", "k": "group", "a": _R,
         "p": "The bilingual Product Monograph (incl. Patient Medication Information) and the labels.",
         "g": "The product-facing documents — all bilingual (English + French).", "u": "pm"},
        {"s": "1.3.1", "t": "Product Monograph (bilingual, incl. PMI)", "k": "document",
         "a": _R, "aff": [_GEN, _UP], "gen": "pm_xml", "fmt": ["xml", "pdf", "docx"], "bi": True,
         "p": "The Product Monograph in English AND French, following the HC Master Template (2024-08-30).",
         "g": "Bilingual is mandatory — the section is only complete when BOTH English and French are present. Author it in-app from the guided bilingual form (Part I Health Professional Information + Part III Patient Medication Information): the portal builds a validated XML Product Monograph AND a readable PDF draft. Or upload each language yourself (PDF; a .docx alongside is expected). Use the current HC Product Monograph Master Template.",
         "u": "pm"},
        {"s": "1.3.2", "t": "Look-alike Sound-alike (LASA) Brand-name Assessment",
         "k": "document", "a": _O, "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"],
         "bi": False,
         "p": "The look-alike / sound-alike safety assessment of the proposed brand name.",
         "g": "Health Canada assesses the proposed brand name against existing products to avoid look-alike/sound-alike confusion. Upload the assessment, or mark N/A if not applicable.",
         "u": "labels"},
        {"s": "1.3.3", "t": "Labelling", "k": "document", "a": _R, "aff": [_GEN, _UP],
         "gen": "structured", "fmt": ["pdf"], "bi": True,
         "p": "Bilingual mock-ups: inner label, outer label, package, and package insert.",
         "g": "Labelling sits at 1.3.3 in the Canadian Module 1 table. Bilingual mock-ups are required at time of submission; min. 10 pt sans-serif (9 pt in tables). Upload the label set (EN + FR).",
         "u": "labels"},
        {"s": "1.4", "t": "Health Canada Summaries", "k": "group", "a": _O,
         "p": "HC-specific summaries. For an ANDS, the comparative-bioequivalence summary (CS-BE) is filed under 1.6.",
         "g": "Health-Canada-specific summaries (e.g. a multidisciplinary tabular summary) — generally optional for a straightforward ANDS.",
         "u": "m1"},
        {"s": "1.5", "t": "Environmental Assessment Statement", "k": "document", "a": _O,
         "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Environmental impact assessment, where required by the product class.",
         "g": "Conditional — include if required for your product; otherwise mark N/A.", "u": "m1"},
        {"s": "1.6", "t": "Regional Clinical Information — Comprehensive Summary–Bioequivalence (CS-BE)",
         "k": "document", "a": _R, "aff": [_GEN, _UP], "gen": "cs_be", "fmt": ["pdf"],
         "bi": False,
         "p": "The Canadian comparative-bioavailability (bioequivalence) summary supporting the ANDS.",
         "g": "The CS-BE electronic copy is placed under 1.6 (regional clinical information), leaf m1-6-cs-be. It summarises the pivotal comparative bioavailability study vs the Canadian Reference Product (AUC/Cmax 90% CI, the applicable ICH-M13A or legacy ruleset). The portal scaffolds it from your CRP + BE-study inputs, or upload the completed CS-BE. The full study report goes in Module 5.3.1.",
         "u": "csbe"},
        {"s": "1.7", "t": "Clinical Trial Information", "k": "group", "a": _O, "na": True,
         "p": "Clinical-trial-specific information.",
         "g": "Applies to Clinical Trial Applications (CTAs), not to an ANDS — not applicable here.",
         "u": "ectd"},
    ]},
    {"module": "2", "title": "Module 2 — CTD Summaries", "nodes": [
        {"s": "2.1", "t": "CTD Table of Contents (Modules 2–5)", "k": "document", "a": _O,
         "aff": [], "gen": None, "fmt": [], "bi": False,
         "p": "The table of contents for Modules 2–5.",
         "g": "Generated automatically by the eCTD backbone — nothing to upload. View it in the Application Viewer.",
         "u": "ectd"},
        {"s": "2.2", "t": "Introduction", "k": "document", "a": _O, "aff": [_GEN, _UP, _NA],
         "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "A brief overview of the drug: pharmacological class, mode of action, and proposed use.",
         "g": "A short introduction to the product. Upload the PDF or mark N/A.", "u": "ectd"},
        {"s": "2.3", "t": "Quality Overall Summary — QOS-CE(BE)", "k": "document", "a": _R,
         "aff": [_GEN, _UP], "gen": "qos_ce_scaffold", "fmt": ["pdf", "docx"], "bi": False,
         "p": "The quality summary of Module 3 — for an ANDS the QOS-CE(BE) bioequivalence-focused variant.",
         "g": "Required for an ANDS and never suppressed. Summarises drug substance + drug product + stability from Module 3 (~40–100 pages). The portal scaffolds the QOS-CE(BE) template; complete or upload it. A .docx is expected alongside the PDF.",
         "u": "qos"},
        {"s": "2.4", "t": "Nonclinical Overview", "k": "document", "a": _O, "sup": True,
         "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Overview of nonclinical (animal) pharmacology/toxicology.",
         "g": "Not required for a generic ANDS relying on comparative bioequivalence — suppressed on the CS-BE path.",
         "u": "ectd"},
        {"s": "2.5", "t": "Clinical Overview", "k": "document", "a": _O, "sup": True,
         "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Overview of clinical efficacy/safety.",
         "g": "Not required for a generic ANDS relying on comparative bioequivalence — suppressed on the CS-BE path.",
         "u": "ectd"},
        {"s": "2.6", "t": "Nonclinical Written & Tabulated Summaries", "k": "document",
         "a": _O, "sup": True, "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Detailed nonclinical summaries.",
         "g": "Not required for a generic ANDS — suppressed on the CS-BE path.", "u": "ectd"},
        {"s": "2.7", "t": "Clinical Summary", "k": "document", "a": _O, "sup": True,
         "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Detailed clinical summary.",
         "g": "Not required for a generic ANDS — suppressed on the CS-BE path.", "u": "ectd"},
    ]},
    {"module": "3", "title": "Module 3 — Quality (CMC)", "nodes": [
        {"s": "3.2.S", "t": "Drug Substance (3.2.S)", "k": "group", "a": _R,
         "p": "The active pharmaceutical ingredient — nomenclature, manufacture, characterization, control, stability.",
         "g": "For an ANDS, specs must be at least as stringent as the reference product.", "u": "cmc"},
        {"s": "3.2.S.1", "t": "General Information (Nomenclature, Structure, Properties)",
         "k": "document", "a": _R, "aff": [_GEN, _UP], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Name, structure and physicochemical properties of the drug substance.",
         "g": "Same expectations as an NDS. Upload the PDF.", "u": "cmc"},
        {"s": "3.2.S.2", "t": "Manufacture", "k": "document", "a": _R, "aff": [_GEN, _UP],
         "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Manufacturer(s) and manufacturing process of the drug substance.",
         "g": "May reference acceptable innovator/DMF data; outline the process if different.", "u": "cmc"},
        {"s": "3.2.S.3", "t": "Characterisation", "k": "document", "a": _R, "aff": [_GEN, _UP],
         "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Elucidation of structure and impurities.",
         "g": "Characterization and impurity profile of the drug substance.", "u": "cmc"},
        {"s": "3.2.S.4", "t": "Control of Drug Substance", "k": "document", "a": _R,
         "aff": [_GEN, _UP], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Specifications, analytical procedures, batch analyses.",
         "g": "Specs at least as stringent as the reference product.", "u": "cmc"},
        {"s": "3.2.S.5", "t": "Reference Standards or Materials", "k": "document", "a": _O,
         "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Reference standards used in testing.", "g": "Upload or mark N/A.", "u": "cmc"},
        {"s": "3.2.S.6", "t": "Container Closure System", "k": "document", "a": _O,
         "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Packaging of the drug substance.", "g": "Include if different from reference; else N/A.", "u": "cmc"},
        {"s": "3.2.S.7", "t": "Stability", "k": "document", "a": _R, "aff": [_GEN, _UP],
         "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Stability data for the drug substance.",
         "g": "Accelerated + long-term stability under the same conditions as the reference.", "u": "cmc"},
        {"s": "3.2.P", "t": "Drug Product (3.2.P)", "k": "group", "a": _R,
         "p": "The finished dosage form — composition, development, manufacture, control, reference standards, container closure, stability.",
         "g": "Must match the reference product for pharmaceutical equivalence. Runs 3.2.P.1 through 3.2.P.8.",
         "u": "cmc"},
        {"s": "3.2.P.1", "t": "Description & Composition", "k": "document", "a": _R,
         "aff": [_GEN, _UP], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Description and composition of the drug product.",
         "g": "Must establish pharmaceutical equivalence to the reference.", "u": "cmc"},
        {"s": "3.2.P.2", "t": "Pharmaceutical Development", "k": "document", "a": _R,
         "aff": [_GEN, _UP], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Development of the formulation.",
         "g": "Justify formulation equivalence; biowaiver justification per ICH M9 if applicable.", "u": "cmc"},
        {"s": "3.2.P.3", "t": "Manufacture", "k": "document", "a": _R, "aff": [_GEN, _UP],
         "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Manufacturer(s) and process for the drug product.",
         "g": "Process description and controls.", "u": "cmc"},
        {"s": "3.2.P.4", "t": "Control of Excipients", "k": "document", "a": _R, "aff": [_GEN, _UP],
         "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Specifications and testing of excipients.", "g": "Excipient control.", "u": "cmc"},
        {"s": "3.2.P.5", "t": "Control of Drug Product", "k": "document", "a": _R, "aff": [_GEN, _UP],
         "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Specifications, analytical procedures, batch analyses of the finished product.",
         "g": "Specs must match or exceed the reference product.", "u": "cmc"},
        {"s": "3.2.P.6", "t": "Reference Standards or Materials", "k": "document", "a": _O,
         "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Reference standards or materials for the drug product.",
         "g": "Upload or mark N/A.", "u": "cmc"},
        {"s": "3.2.P.7", "t": "Container Closure System", "k": "document", "a": _R,
         "aff": [_GEN, _UP], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "The drug product's container closure system.",
         "g": "Description and suitability of the packaging; samples may be required.", "u": "cmc"},
        {"s": "3.2.P.8", "t": "Stability", "k": "document", "a": _R, "aff": [_GEN, _UP],
         "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Stability data for the drug product.",
         "g": "Accelerated + long-term; ≥3 batches; conditions matching the approved reference.", "u": "cmc"},
        {"s": "3.2.R", "t": "Regional Information", "k": "document", "a": _O,
         "aff": [_GEN, _UP, _NA], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Canada-specific quality information (e.g. a device component).",
         "g": "Usually omitted for a chemical-entity ANDS unless a device is used; else N/A.", "u": "cmc"},
        {"s": "3.3", "t": "Literature References", "k": "document", "a": _O, "aff": [_GEN, _UP, _NA],
         "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "Supporting quality literature.", "g": "Optional. Upload or mark N/A.", "u": "cmc"},
    ]},
    {"module": "4", "title": "Module 4 — Nonclinical Study Reports", "nodes": [
        {"s": "4", "t": "Nonclinical Study Reports", "k": "group", "a": _O, "na": True,
         "p": "Animal pharmacology/toxicology study reports.",
         "g": "NOT applicable to a generic ANDS relying on comparative bioequivalence — the generic relies on the reference product's established nonclinical profile.",
         "u": "ectd"},
    ]},
    {"module": "5", "title": "Module 5 — Clinical Study Reports", "nodes": [
        {"s": "5.3.1", "t": "Comparative Bioavailability / Bioequivalence Study Reports",
         "k": "document", "a": _R, "aff": [_GEN, _UP], "gen": "structured", "fmt": ["pdf"], "bi": False,
         "p": "The pivotal comparative BA/BE study report(s) — the core evidence for an ANDS.",
         "g": "REQUIRED for every ANDS. The pivotal PK crossover study vs. the Canadian Reference Product; the 90% CI for AUC and Cmax must fall within 80–125% (log-scale). Includes protocol, PK data, statistics and safety. Upload the study report(s).",
         "u": "babe"},
    ]},
]


def _slug(section: str) -> str:
    return section.replace(".", "-").lower()


def _folder(module: str, section: str) -> str:
    entry = ectd.placement_for_heading(section)
    if entry:
        return entry["folder"]
    if module == "1":
        return f"m1/ca/{_slug(section)}"
    return f"m{module}/{_slug(section)}"


def _leaf_id(section: str) -> str:
    return ectd.leaf_id_for(section) or f"m{_slug(section)}"


# --- submission-type applicability overlay (comprehensive drug-type support) --
# The eCTD backbone (M1–M5, every section) is SHARED across submission types;
# what differs per type is which sections are required / optional / na. These are
# deterministic Health Canada / ICH module-applicability facts — not authoring.
#
# GENERIC-ONLY artifacts a brand/DIN filing never carries: the Form V patent
# declaration (1.2.4, PM(NOC) s.5), the Comprehensive Summary–Bioequivalence
# (1.6) and the comparative-BE study report (5.3.1).
_GENERIC_ONLY = {"1.2.4", "1.6", "5.3.1"}
_GENERIC_FAMILY = {"ANDS", "SANDS"}

# Honest scope: ANDS Studio is purpose-built for ANDS (generics). It reports the
# CORRECT eCTD structure/applicability + validation + fees for other types, but
# its in-app authoring generators are ANDS-tuned — stated plainly, never hidden.
_SCOPE_NOTES = {
    "NDS": "ANDS Studio is purpose-built for Abbreviated New Drug Submissions "
           "(generics). This New Drug Submission (innovator) shows the correct "
           "eCTD module applicability — the full nonclinical (Module 4) and "
           "clinical/nonclinical summaries (2.4–2.7) are required, and no Form V "
           "or comparative-bioequivalence study applies — but the scientific "
           "dossier is authored outside ANDS Studio.",
    "SNDS": "ANDS Studio is purpose-built for Abbreviated New Drug Submissions "
            "(generics). This Supplement to a New Drug Submission (brand change) "
            "carries no Form V or comparative-bioequivalence study; the changed "
            "scientific modules are authored outside ANDS Studio.",
    "DIN": "ANDS Studio is purpose-built for Abbreviated New Drug Submissions "
           "(generics). A DIN Application is a lighter regulatory route — the "
           "administrative Module 1 and product information apply; the full "
           "CMC/clinical generic dossier does not.",
}


def _applicability(node: dict, module: str, cs_be_only: bool,
                   submission_type: str = "ANDS") -> str:
    st = str(submission_type or "ANDS").upper()
    sec = node["s"]
    # Module 4 (nonclinical study reports): only the innovator NDS requires it.
    if module == "4" or node.get("na"):
        if st == "NDS" and module == "4":
            return "required"
        return "na"
    # generic-only artifacts (Form V / CS-BE / comparative-BE study report)
    if sec in _GENERIC_ONLY:
        if st == "ANDS":
            return node.get("a", _O)          # required for a generic ANDS
        if st == "SANDS":
            return "conditional"              # a generic supplement may not touch these
        return "na"                           # NDS / SNDS / DIN never file these
    # 2.4–2.7 nonclinical/clinical summaries (base-flagged cs_be_suppressed):
    # an innovator NDS requires the full set; the generic path suppresses them.
    if node.get("sup"):
        if st == "NDS":
            return "required"
        if st in _GENERIC_FAMILY and cs_be_only:
            return "suppressed"
        return node.get("a", _O)
    # DIN Application: the heavy CMC (M3) / clinical (M5) dossier is not the DINA
    # route — keep admin + product info required, downgrade heavy technical.
    if st == "DIN" and module in ("3", "5") and node.get("a") == _R:
        return "optional"
    return node.get("a", _O)


def _build_node(module: str, node: dict, cs_be_only: bool,
                submission_type: str = "ANDS") -> dict:
    section = node["s"]
    url_key = node.get("u", "ectd")
    return {
        "id": _slug(section),
        "module": module,
        "section": section,
        "title": node["t"],
        "kind": node["k"],
        "depth": section.count("."),
        "applicability": _applicability(node, module, cs_be_only, submission_type),
        "affordances": list(node.get("aff", [])),
        "generator_key": node.get("gen"),
        "ai_draftable": node.get("gen") in LLM_DRAFTABLE,
        "formats": list(node.get("fmt", [])),
        "bilingual": bool(node.get("bi")),
        "purpose": node.get("p", ""),
        "guidance": node.get("g", ""),
        "source_url": _URL.get(url_key, _URL["ectd"]),
        "folder": _folder(module, section),
        "leaf_id": _leaf_id(section),
    }


def section_tree(*, cs_be_only: bool = True,
                 submission_type: str = "ANDS") -> dict:
    """The full versioned M1–M5 tree with per-section applicability resolved for
    the submission type (NDS / ANDS / SANDS / SNDS / DIN)."""
    st = str(submission_type or "ANDS").upper()
    modules = []
    for mod in _MODULES:
        nodes = [_build_node(mod["module"], n, cs_be_only, st)
                 for n in mod["nodes"]]
        modules.append({"module": mod["module"], "title": mod["title"], "nodes": nodes})
    return {"version": SECTION_TREE_VERSION, "cs_be_only": bool(cs_be_only),
            "submission_type": st, "scope_note": _SCOPE_NOTES.get(st),
            "modules": modules}


def all_nodes(*, cs_be_only: bool = True,
              submission_type: str = "ANDS") -> list[dict]:
    return [n for m in section_tree(cs_be_only=cs_be_only,
                                    submission_type=submission_type)["modules"]
            for n in m["nodes"]]


def module_sections(module: str, *, cs_be_only: bool = True,
                    submission_type: str = "ANDS") -> list[dict]:
    module = str(module or "").strip()
    for m in section_tree(cs_be_only=cs_be_only,
                          submission_type=submission_type)["modules"]:
        if m["module"] == module:
            return m["nodes"]
    return []


def node_for(section: str, *, cs_be_only: bool = True,
             submission_type: str = "ANDS") -> dict | None:
    section = str(section or "").strip()
    return next((n for n in all_nodes(cs_be_only=cs_be_only,
                                      submission_type=submission_type)
                 if n["section"] == section), None)


def node_for_id(node_id: str, *, cs_be_only: bool = True,
                submission_type: str = "ANDS") -> dict | None:
    node_id = str(node_id or "").strip()
    return next((n for n in all_nodes(cs_be_only=cs_be_only,
                                      submission_type=submission_type)
                 if n["id"] == node_id), None)
