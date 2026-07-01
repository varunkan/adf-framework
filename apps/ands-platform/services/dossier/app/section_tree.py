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

# module -> (title, [nodes]); cs_be_suppressed marked per-node.
_MODULES: list[dict] = [
    {"module": "1", "title": "Module 1 — Administrative & regional (Canada)", "nodes": [
        {"s": "1.0", "t": "Cover Letter", "k": "document", "a": _R,
         "aff": [_GEN, _UP], "gen": "cover_letter", "fmt": ["pdf"], "bi": False,
         "p": "Your submission's cover letter — who you are, what you're filing, and the dossier it belongs to.",
         "g": "Health Canada gives you the placement slot; the portal generates the letter from your dossier/company/product details. It addresses the submission, names the activity type and sequence, and lists your contacts. You can generate it here or upload your own.",
         "u": "m1"},
        {"s": "1.2", "t": "Administrative Information", "k": "group", "a": _R,
         "p": "The regulatory/administrative package — application form, patents, fees, certifications, authorizations.",
         "g": "Everything Health Canada needs to process the submission administratively. Complete each item below.",
         "u": "m1"},
        {"s": "1.2.1", "t": "Drug Submission Application Form", "k": "document",
         "a": _R, "aff": [_GEN, _UP], "gen": "rep_application_form", "fmt": ["pdf"],
         "bi": False,
         "p": "The application form — since Oct 2020 this is the Regulatory Enrolment Process (REP) template, not the old HC/SC 3011.",
         "g": "Identifies the sponsor (Company ID), the product, the Dossier ID, the regulatory activity type and the sequence. The portal generates the REP CO/RT/PI templates from your single set of identifiers (no re-keying); or upload the completed REP XML.",
         "u": "rep"},
        {"s": "1.2.2", "t": "Information on Prior-Related Applications", "k": "document",
         "a": _O, "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Cross-references to any prior or related submissions for this product.",
         "g": "List related Dossier IDs / submissions (e.g. a linked NDS, a Master File). Mark N/A if there are none.",
         "u": "m1"},
        {"s": "1.2.4", "t": "Labels & Packages — Certification + bilingual mock-ups",
         "k": "document", "a": _R, "aff": [_UP], "gen": None, "fmt": ["pdf"], "bi": True,
         "p": "The Labels & Packages Certification Form plus bilingual mock-ups of the inner label, outer label, package and insert.",
         "g": "Bilingual (English + French) mock-ups are required at time of submission; min. 10 pt sans-serif (9 pt in tables). Upload the certification form and the mock-ups.",
         "u": "labels"},
        {"s": "1.2.5", "t": "Patent Information (Form IV — Patent List)", "k": "document",
         "a": _R, "aff": [_GEN, _UP], "gen": "patent_form_iv", "fmt": ["pdf"], "bi": False,
         "p": "For an ANDS: address the patents/CSPs on the Patent Register for the Canadian Reference Product.",
         "g": "Complete Form IV (Patent List) under the Patented Medicines (Notice of Compliance) Regulations. The portal scaffolds the form from your reference-product + patent inputs, or upload a completed Form IV.",
         "u": "forms"},
        {"s": "1.2.6", "t": "ANDS Sponsor Attestation", "k": "document", "a": _R,
         "aff": [_GEN, _UP], "gen": "ands_attestation", "fmt": ["pdf"], "bi": False,
         "p": "The sponsor's signed attestation that the ANDS is accurate, complete and not misleading.",
         "g": "Required for an ANDS (not for SANDS or labelling-only). Note the ANDS Sponsor Attestation Checklist is requested from Health Canada by email, not on the public forms page. The portal produces the attestation for signature; or upload the signed form.",
         "u": "forms"},
        {"s": "1.2.7", "t": "Fees / Small-business forms", "k": "document", "a": _R,
         "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Fee payment information — and, if you qualify, the small-business status confirmation.",
         "g": "Fees follow the Fees Order (CPI-indexed each April 1). Small-business status (≤300 staff or <$100M revenue, incl. affiliates) gives a 50% pre-market reduction and a full waiver on your first-ever submission — but status must be GRANTED BEFORE you file. Upload the fee/small-business form.",
         "u": "fees"},
        {"s": "1.2.8", "t": "Regulatory correspondence & authorizations", "k": "document",
         "a": _O, "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Contact information and authorization letters (sponsor, regulatory, quality contacts).",
         "g": "Sponsor & technical/safety contacts and any authorization letters. Mark N/A if not applicable.",
         "u": "m1"},
        {"s": "1.3", "t": "Product Information", "k": "group", "a": _R,
         "p": "The bilingual Product Monograph, Patient Medication Information, and labels.",
         "g": "The product-facing documents — all bilingual.", "u": "pm"},
        {"s": "1.3.1", "t": "Product Monograph (bilingual)", "k": "document", "a": _R,
         "aff": [_UP], "gen": None, "fmt": ["pdf", "docx"], "bi": True,
         "p": "The Product Monograph in English AND French, following the HC Master Template (2024-08-30).",
         "g": "Bilingual is mandatory — the section is only complete when BOTH English and French are present. Use the current HC Product Monograph Master Template. Upload each language (PDF; a .docx alongside is expected).",
         "u": "pm"},
        {"s": "1.3.2", "t": "Patient Medication Information (PMI)", "k": "document",
         "a": _R, "aff": [_UP], "gen": None, "fmt": ["pdf"], "bi": True,
         "p": "Plain-language medication information for patients — written at a Grade 6–8 reading level.",
         "g": "Bilingual, plain-language (Grade 6–8). Usually part of the Product Monograph but treated as its own section. Upload EN + FR.",
         "u": "pmi"},
        {"s": "1.3.3", "t": "Labelling", "k": "document", "a": _R, "aff": [_UP],
         "gen": None, "fmt": ["pdf"], "bi": True,
         "p": "Bilingual mock-ups: inner label, outer label, package, and insert.",
         "g": "Bilingual mock-ups, min. 10 pt sans-serif. Upload the label set.", "u": "labels"},
        {"s": "1.4", "t": "Health Canada Summaries", "k": "group", "a": _C,
         "p": "HC-specific summaries — for an ANDS, the Comprehensive Summary–Bioequivalence.",
         "g": "Conditional summaries specific to Health Canada.", "u": "m1"},
        {"s": "1.4.2", "t": "Comprehensive Summary — Bioequivalence (CS-BE)", "k": "document",
         "a": _R, "aff": [_GEN, _UP], "gen": "cs_be", "fmt": ["pdf"], "bi": False,
         "p": "Summarises the pivotal comparative bioavailability (bioequivalence) studies supporting the ANDS.",
         "g": "Recommended for an ANDS; standardises the BE evidence. The portal scaffolds the CS-BE from your CRP + BE-study inputs (AUC/Cmax, the applicable ICH-M13A or legacy ruleset); or upload the completed CS-BE.",
         "u": "csbe"},
        {"s": "1.5", "t": "Environmental Assessment Statement", "k": "document", "a": _C,
         "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Environmental impact assessment, where required by the product class.",
         "g": "Conditional — include if required for your product; otherwise mark N/A.", "u": "m1"},
        {"s": "1.6", "t": "Regional clinical information / CS-BE electronic copy",
         "k": "document", "a": _O, "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Canadian-specific clinical/regional information — e.g. the CS-BE electronic copy.",
         "g": "Optional Canadian regional clinical info. Mark N/A if not applicable.", "u": "m1"},
    ]},
    {"module": "2", "title": "Module 2 — CTD Summaries", "nodes": [
        {"s": "2.2", "t": "Introduction", "k": "document", "a": _R, "aff": [_UP],
         "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "A brief overview of the drug: pharmacological class, mode of action, and proposed use.",
         "g": "One-page introduction to the product. Upload the PDF.", "u": "ectd"},
        {"s": "2.3", "t": "Quality Overall Summary — QOS-CE(BE)", "k": "document", "a": _R,
         "aff": [_GEN, _UP], "gen": "qos_ce_scaffold", "fmt": ["pdf", "docx"], "bi": False,
         "p": "The quality summary of Module 3 — for an ANDS the QOS-CE(BE) bioequivalence-focused variant.",
         "g": "Required for an ANDS and never suppressed. Summarises drug substance + drug product + stability from Module 3 (~40–100 pages). The portal scaffolds the QOS-CE(BE) template; complete or upload it. A .docx is expected alongside the PDF.",
         "u": "qos"},
        {"s": "2.4", "t": "Nonclinical Overview", "k": "document", "a": _O, "sup": True,
         "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Overview of nonclinical (animal) pharmacology/toxicology.",
         "g": "Not required for a generic ANDS relying on comparative bioequivalence — suppressed on the CS-BE path.",
         "u": "ectd"},
        {"s": "2.5", "t": "Clinical Overview", "k": "document", "a": _O, "sup": True,
         "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Overview of clinical efficacy/safety.",
         "g": "Not required for a generic ANDS relying on comparative bioequivalence — suppressed on the CS-BE path.",
         "u": "ectd"},
        {"s": "2.6", "t": "Nonclinical Written & Tabulated Summaries", "k": "document",
         "a": _O, "sup": True, "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Detailed nonclinical summaries.",
         "g": "Not required for a generic ANDS — suppressed on the CS-BE path.", "u": "ectd"},
        {"s": "2.7", "t": "Clinical Summary", "k": "document", "a": _O, "sup": True,
         "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Detailed clinical summary.",
         "g": "Not required for a generic ANDS — suppressed on the CS-BE path.", "u": "ectd"},
    ]},
    {"module": "3", "title": "Module 3 — Quality (CMC)", "nodes": [
        {"s": "3.2.S", "t": "Drug Substance (3.2.S)", "k": "group", "a": _R,
         "p": "The active pharmaceutical ingredient — nomenclature, manufacture, characterization, control, stability.",
         "g": "For an ANDS, specs must be at least as stringent as the reference product.", "u": "cmc"},
        {"s": "3.2.S.1", "t": "Nomenclature, Structure & Properties", "k": "document",
         "a": _R, "aff": [_UP], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Name, structure and physicochemical properties of the drug substance.",
         "g": "Same expectations as an NDS. Upload the PDF.", "u": "cmc"},
        {"s": "3.2.S.2", "t": "Manufacture", "k": "document", "a": _R, "aff": [_UP],
         "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Manufacturer(s) and manufacturing process of the drug substance.",
         "g": "May reference acceptable innovator/DMF data; outline the process if different.", "u": "cmc"},
        {"s": "3.2.S.3", "t": "Characterization", "k": "document", "a": _R, "aff": [_UP],
         "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Elucidation of structure and impurities.",
         "g": "Characterization and impurity profile of the drug substance.", "u": "cmc"},
        {"s": "3.2.S.4", "t": "Control of Drug Substance", "k": "document", "a": _R,
         "aff": [_UP], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Specifications, analytical procedures, batch analyses.",
         "g": "Specs at least as stringent as the reference product.", "u": "cmc"},
        {"s": "3.2.S.5", "t": "Reference Standards or Materials", "k": "document", "a": _O,
         "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Reference standards used in testing.", "g": "Upload or mark N/A.", "u": "cmc"},
        {"s": "3.2.S.6", "t": "Container Closure System", "k": "document", "a": _O,
         "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Packaging of the drug substance.", "g": "Include if different from reference; else N/A.", "u": "cmc"},
        {"s": "3.2.S.7", "t": "Stability", "k": "document", "a": _R, "aff": [_UP],
         "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Stability data for the drug substance.",
         "g": "Accelerated + long-term stability under the same conditions as the reference.", "u": "cmc"},
        {"s": "3.2.P", "t": "Drug Product (3.2.P)", "k": "group", "a": _R,
         "p": "The finished dosage form — composition, development, manufacture, control, stability.",
         "g": "Must match the reference product for pharmaceutical equivalence.", "u": "cmc"},
        {"s": "3.2.P.1", "t": "Description & Composition", "k": "document", "a": _R,
         "aff": [_UP], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Description and composition of the drug product.",
         "g": "Must establish pharmaceutical equivalence to the reference.", "u": "cmc"},
        {"s": "3.2.P.2", "t": "Pharmaceutical Development", "k": "document", "a": _R,
         "aff": [_UP], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Development of the formulation.",
         "g": "Justify formulation equivalence; biowaiver justification per ICH M9 if applicable.", "u": "cmc"},
        {"s": "3.2.P.3", "t": "Manufacture", "k": "document", "a": _R, "aff": [_UP],
         "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Manufacturer(s) and process for the drug product.",
         "g": "Process description and controls.", "u": "cmc"},
        {"s": "3.2.P.4", "t": "Control of Excipients", "k": "document", "a": _R, "aff": [_UP],
         "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Specifications and testing of excipients.", "g": "Excipient control.", "u": "cmc"},
        {"s": "3.2.P.5", "t": "Control of Drug Product", "k": "document", "a": _R, "aff": [_UP],
         "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Specifications, analytical procedures, batch analyses of the finished product.",
         "g": "Specs must match or exceed the reference product.", "u": "cmc"},
        {"s": "3.2.P.7", "t": "Stability", "k": "document", "a": _R, "aff": [_UP],
         "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Stability data for the drug product.",
         "g": "Accelerated + long-term; ≥3 batches; conditions matching the approved reference.", "u": "cmc"},
        {"s": "3.2.R", "t": "Regional Information", "k": "document", "a": _O,
         "aff": [_UP, _NA], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Canada-specific quality information (e.g. a device component).",
         "g": "Usually omitted for a chemical-entity ANDS unless a device is used; else N/A.", "u": "cmc"},
        {"s": "3.3", "t": "Literature References", "k": "document", "a": _O, "aff": [_UP, _NA],
         "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "Supporting quality literature.", "g": "Optional. Upload or mark N/A.", "u": "cmc"},
    ]},
    {"module": "4", "title": "Module 4 — Nonclinical Study Reports", "nodes": [
        {"s": "4", "t": "Nonclinical Study Reports", "k": "group", "a": _O,
         "p": "Animal pharmacology/toxicology study reports.",
         "g": "NOT applicable to a generic ANDS relying on comparative bioequivalence — the generic relies on the reference product's established nonclinical profile.",
         "u": "ectd"},
    ]},
    {"module": "5", "title": "Module 5 — Clinical Study Reports", "nodes": [
        {"s": "5.3.1", "t": "Comparative Bioavailability / Bioequivalence Study Reports",
         "k": "document", "a": _R, "aff": [_UP], "gen": None, "fmt": ["pdf"], "bi": False,
         "p": "The pivotal comparative BA/BE study report(s) — the core evidence for an ANDS.",
         "g": "REQUIRED for every ANDS. The pivotal PK crossover study vs. the Canadian Reference Product; the 90% CI for AUC and Cmax must fall within 80–125%. Includes protocol, PK data, statistics and safety. Upload the study report(s).",
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


def _applicability(node: dict, module: str, cs_be_only: bool) -> str:
    if module == "4":
        return "na"
    if cs_be_only and node.get("sup"):
        return "suppressed"
    return node.get("a", _O)


def _build_node(module: str, node: dict, cs_be_only: bool) -> dict:
    section = node["s"]
    url_key = node.get("u", "ectd")
    return {
        "id": _slug(section),
        "module": module,
        "section": section,
        "title": node["t"],
        "kind": node["k"],
        "depth": section.count("."),
        "applicability": _applicability(node, module, cs_be_only),
        "affordances": list(node.get("aff", [])),
        "generator_key": node.get("gen"),
        "formats": list(node.get("fmt", [])),
        "bilingual": bool(node.get("bi")),
        "purpose": node.get("p", ""),
        "guidance": node.get("g", ""),
        "source_url": _URL.get(url_key, _URL["ectd"]),
        "folder": _folder(module, section),
        "leaf_id": _leaf_id(section),
    }


def section_tree(*, cs_be_only: bool = True) -> dict:
    """The full versioned M1–M5 tree with per-section applicability resolved."""
    modules = []
    for mod in _MODULES:
        nodes = [_build_node(mod["module"], n, cs_be_only) for n in mod["nodes"]]
        modules.append({"module": mod["module"], "title": mod["title"], "nodes": nodes})
    return {"version": SECTION_TREE_VERSION, "cs_be_only": bool(cs_be_only),
            "modules": modules}


def all_nodes(*, cs_be_only: bool = True) -> list[dict]:
    return [n for m in section_tree(cs_be_only=cs_be_only)["modules"]
            for n in m["nodes"]]


def module_sections(module: str, *, cs_be_only: bool = True) -> list[dict]:
    module = str(module or "").strip()
    for m in section_tree(cs_be_only=cs_be_only)["modules"]:
        if m["module"] == module:
            return m["nodes"]
    return []


def node_for(section: str, *, cs_be_only: bool = True) -> dict | None:
    section = str(section or "").strip()
    return next((n for n in all_nodes(cs_be_only=cs_be_only)
                 if n["section"] == section), None)


def node_for_id(node_id: str, *, cs_be_only: bool = True) -> dict | None:
    node_id = str(node_id or "").strip()
    return next((n for n in all_nodes(cs_be_only=cs_be_only)
                 if n["id"] == node_id), None)
