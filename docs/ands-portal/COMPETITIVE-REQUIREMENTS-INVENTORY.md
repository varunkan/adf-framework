# ANDS Platform — Competitive Requirements Inventory

**Document:** `COMPETITIVE-REQUIREMENTS-INVENTORY.md`  
**Version:** 1.0  
**Date:** 2026-06-27  
**Method:** Structured review of vendors serving **Health Canada eCTD / ANDS** workflows, cross-checked against HC primary sources and the existing [`requirements-corrected.json`](requirements-corrected.json) corpus.  
**Companion:** [`VISION-GAP-REQUIREMENTS.md`](VISION-GAP-REQUIREMENTS.md) v2.0 (gap delta + new REQ IDs)

---

## 1. Scope and method

### 1.1 Vendors in the review loop

Each vendor was reviewed for **published product capabilities**, **HC/Canada positioning**, and **SaaS/commercial model** (not pricing quotes).

| # | Vendor / product | Role in ANDS market | Primary sources |
|---|------------------|---------------------|-----------------|
| V1 | **LORENZ docuBridge** (+ ONE/TWO/FIVE) | Leading eCTD publisher; CA eCTD profile via eValidator | lorenz.cc, IntuitionLabs 2026 |
| V2 | **LORENZ eValidator** (Basic/ONE/FIVE) | Industry-standard HC technical validation | lorenz.cc validation profiles |
| V3 | **LORENZ drugTrack** | RIM / product lifecycle adjacent to publishing | lorenz.cc/drugTrack |
| V4 | **LORENZ verifAI / Content Validator** | AI content completeness vs ICH/FDA/EMA | lorenz.cc/verifAI |
| V5 | **LORENZ Automator** | Gateway transmission & workflow automation | docuBridge whats-new |
| V6 | **EXTEDO eCTDmanager / EXTEDOpulse** | Global publisher + validator; CESG/ESG | extedo.com |
| V7 | **Veeva Vault RIM Submissions Publishing** | Enterprise cloud RIM + continuous publish/validate | veeva.com, Vault Help |
| V8 | **Certara GlobalSubmit PUBLISH** | Validation-first cloud publisher | certara.com |
| V9 | **Phlexglobal PhlexSubmission** (+ PhlexNeuron) | CRO/service-provider cloud engine | phlexglobal.com, Assyro 2026 |
| V10 | **Ennov Regulatory / eCTD 247** | Cloud-native full suite + lightweight eCTD SaaS | ennov.com, ectd247.com |
| V11 | **MasterControl** (+ Lorenz integration) | QMS/document control feeding publishing | IntuitionLabs comparison |
| V12 | **Assyro AI** | AI-native validation + co-authoring challenger | assyro.com 2026 |
| V13 | **Service providers** (AXSource, EXTEDO services, Freyr) | Outsourced publish/file model | axsource.com, extedo.com/services |
| V14 | **Health Canada** (regulatory benchmark) | Defines mandatory behaviour, not a product | canada.ca CESG/eCTD/REP |

### 1.2 Requirement extraction rules

For each vendor feature we recorded:

1. **COMP-ID** — stable identifier (`COMP-xxx-yyy`)
2. **Statement** — testable SHALL language
3. **Priority** — MUST (table stakes), SHOULD (common in paid tools), COULD (differentiator)
4. **Basis** — `HC-mandate` | `ESG-mandate` | `industry-standard` | `vendor-differentiator` | `SaaS-product`
5. **Our status** — `implemented` | `partial` | `simulated` | `missing` (against current monolith + v1 gap doc)

---

## 2. Master requirement taxonomy (industry synthesis)

Requirements below are **synthesized from the vendor loop**. They represent what sponsors expect when comparing tools for **Canadian ANDS** filing.

### 2.1 Publishing & dossier assembly (COMP-PUB)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-PUB-001 | Visual eCTD tree editor with drag-and-drop leaf placement per HC Module 1 table | MUST | V1, V6, V7, V8, V10 | partial (workspace UI) |
| COMP-PUB-002 | Publish **current view** + lifecycle ops (new/replace/delete/append) with explicit per-leaf status | MUST | V1, V6, V8 | implemented |
| COMP-PUB-003 | **Import** existing third-party eCTD sequences into workspace for follow-up sequences | SHOULD | V1 FIVE | missing |
| COMP-PUB-004 | **Incremental publish** — update only changed leaves without full rebuild | SHOULD | V6 | missing |
| COMP-PUB-005 | Multi-format output from one project (eCTD + NeeS + HTML/PDF archive) | COULD | V1 | missing |
| COMP-PUB-006 | **Application Viewer** — inspect full sequence (Files view + XML Outline view) post-publish | SHOULD | V1 v25+ | missing |
| COMP-PUB-007 | Node Content Pane for complex multi-operation sequences | COULD | V1 | missing |
| COMP-PUB-008 | Auto-generate index.xml, ca-regional.xml, index-md5.txt, util/ DTD bundle | MUST | all | partial (stand-in DTD) |
| COMP-PUB-009 | **software_version** element in RT/MF XML per HC rule F0/I-series | MUST | HC rules | partial |
| COMP-PUB-010 | Single-entry assembly: one metadata set → RT + ca-regional + cover letter | MUST | V1, V6 | implemented |
| COMP-PUB-011 | **Parallel submissions** tracker (same product, multiple regions/activities) | SHOULD | V6 | missing |
| COMP-PUB-012 | **Critical submission** flag + expedited workflow | COULD | V6 | missing |
| COMP-PUB-013 | Grouped / bundled submission support (FDA grouped; pattern for multi-DIN) | COULD | V6 | missing |

### 2.2 Validation — technical (COMP-VAL)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-VAL-001 | **CA eCTD (Health Canada)** validation profile matching official rules v5.3+ | MUST | V1, V2, V6, V8 | partial (stand-in ruleset) |
| COMP-VAL-002 | **CA Non-eCTD** validation profile for legacy/mandatory non-eCTD activities | SHOULD | V2 | missing |
| COMP-VAL-003 | **Live / continuous validation** during assembly, not only at export | MUST | V7, V8 | partial (inline gutter) |
| COMP-VAL-004 | 200+ technical checks incl. 40+ PDF-specific checks (bookmarks, fonts, hyperlinks) | SHOULD | V8 | partial |
| COMP-VAL-005 | **Extended / GRP profiles** — stricter checks beyond agency minimum | SHOULD | V2 FIVE | missing |
| COMP-VAL-006 | **Batch validation** of multiple sequences (server-side) | SHOULD | V2 FIVE | missing |
| COMP-VAL-007 | **eValidator-class parity** — sponsor can cite same engine family as industry | COULD | V2 | missing |
| COMP-VAL-008 | MD5/SHA256 proofreader profile | SHOULD | V2 | partial (MD5 only) |
| COMP-VAL-009 | Validation report export (PDF + structured JSON) for QA sign-off | MUST | V2, V8 | partial |
| COMP-VAL-010 | **CrossCheck** — side-by-side hyperlink/bookmark destination verification | SHOULD | V8 | missing |
| COMP-VAL-011 | Pre-submission **validation report** matching HC emailed report schema | MUST | HC | partial (text ingest) |
| COMP-VAL-012 | Validator **release tied to HC rule updates** without code deploy | MUST | V1, V2, V10 | partial (REQ-040) |

### 2.3 Validation — content & cross-document (COMP-CNT)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-CNT-001 | **Cross-document consistency** (metadata vs PDF titles, orphan files) | MUST | V1, V8, V12 | partial |
| COMP-CNT-002 | **Cross-sequence consistency** vs prior approved sequences | SHOULD | V4, V1 AI | missing |
| COMP-CNT-003 | **AI / semantic content validation** — completeness vs ICH/FDA/HC guidance | COULD | V4, V12 | missing |
| COMP-CNT-004 | Module 2 ↔ Module 3 ↔ Module 5 **data mismatch** detection | COULD | V12 | missing |
| COMP-CNT-005 | **Regulatory change alerts** when HC guidance affects active dossiers | COULD | V12 | missing |
| COMP-CNT-006 | Word-authoring plugin validating while drafting | COULD | V4 | missing |
| COMP-CNT-007 | Compare dossier to **historical approved** content (variation workflows) | COULD | V4 | missing |

### 2.4 PDF remediation & document quality (COMP-PDF)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-PDF-001 | Auto **bookmark** generation for PDFs >10 pages (single-action) | SHOULD | V6, V8, V10, EXTEDO services | partial |
| COMP-PDF-002 | Auto **hyperlink** creation (text → relative internal links) | MUST | V6, V8, V10 | partial |
| COMP-PDF-003 | **Fix PDFs** — fonts embed, OCR, remove encryption, strip Track Changes | MUST | V10 Ennov, EXTEDO services | partial |
| COMP-PDF-004 | **Fix Word** source docs before PDF conversion | SHOULD | V10 | missing |
| COMP-PDF-005 | PDF version 1.4–1.7 enforcement | MUST | all | partial |
| COMP-PDF-006 | DRM/IRM/restricted-access detection | MUST | HC | partial |
| COMP-PDF-007 | A03a/A03b size band warn/block (150–200 MB / ≥200 MB) | MUST | HC | partial |
| COMP-PDF-008 | Literature reference bookmark exemptions (3.3/4.3/5.4) | SHOULD | HC | partial |
| COMP-PDF-009 | **Future-proof archiving** format for long-term retention | COULD | V10 | missing |

### 2.5 Transmission & gateways (COMP-TRN)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-TRN-001 | **FDA ESG NextGen** Test + Production paths | MUST | V6, V7, V13 | simulated |
| COMP-TRN-002 | **Direct gateway integration** from UI (submit without manual WebTrader upload) | MUST | V7, V5 Automator | missing |
| COMP-TRN-003 | EMA eSubmission Gateway (for global vendors; pattern for multi-HA) | COULD | V7 | n/a (HC focus) |
| COMP-TRN-004 | **Automated ack polling** + operator alerts | MUST | V5, V7 | simulated |
| COMP-TRN-005 | **Physical media** package + shipping instructions + receipt reconciliation | MUST | V13, HC | partial |
| COMP-TRN-006 | Post-16:30 EST scheduling guidance for 5–10 GB packages | COULD | HC | partial |
| COMP-TRN-007 | **Query management** to HC post-submission | SHOULD | V13 AXSource | missing |
| COMP-TRN-008 | Transmission **runbook wizard** for first-time ESG sponsors | SHOULD | V13 EXTEDO services | missing |

### 2.6 RIM, planning & submission operations (COMP-RIM)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-RIM-001 | **Submission content plan** — HA templates, tasks, deadlines, bulk assignment | MUST | V7, V10 | missing |
| COMP-RIM-002 | **Submission planning** — link product, indication, country, activity, target date | MUST | V7, V8, V3 | partial (portfolio REQ-047) |
| COMP-RIM-003 | **Registration tracking** per product × country × status | SHOULD | V7, V3, V10 | missing |
| COMP-RIM-004 | **Health authority correspondence** log (letters, emails, commitments) | SHOULD | V7, V10 | missing |
| COMP-RIM-005 | **Continuous publishing** — auto-republish when source doc changes | SHOULD | V7 | missing |
| COMP-RIM-006 | **Submission-independent hyperlinks** reusable across submissions | SHOULD | V7 | missing |
| COMP-RIM-007 | **Document reuse detection** across submissions in same market | SHOULD | V7 | missing |
| COMP-RIM-008 | **Approved view** — only QA-approved content eligible for publish | SHOULD | V10 | partial (esign gate) |
| COMP-RIM-009 | **Metadata-based search** across dossiers (not folder-only) | SHOULD | V10 | missing |
| COMP-RIM-010 | **Drag-drop dossier reuse** across regions (clone CA tree from US core) | COULD | V10 | missing |
| COMP-RIM-011 | **DIA EDM Reference Model** pre-config for document types | COULD | eCTD 247 | missing |
| COMP-RIM-012 | **SNDS / SANDS / NC** activity templates alongside ANDS | MUST | HC | partial (REQ-004 router) |
| COMP-RIM-013 | **DIN registry** + marketed product linkage post-NOC | SHOULD | V3, generics need | missing |
| COMP-RIM-014 | **Right-to-sell fee** calendar + Oct-1 statutory reminders | SHOULD | HC | partial (REQ-037) |

### 2.7 Canada-specific ANDS / Module 1 (COMP-CA)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-CA-001 | **Bilingual Product Monograph** (EN + FR) workflow for prescription ANDS | MUST | HC, V13 | missing |
| COMP-CA-002 | **XML Product Monograph** generation/validation (HC XML PM rules + CV) | MUST | HC 2024+ | missing |
| COMP-CA-003 | Annotated PM cross-references to Module 2 / 1.4.2 Bioequivalence Summary | MUST | HC placement table | missing |
| COMP-CA-004 | **Submission Certification Form** for NDS/SNDS/ANDS/SANDS/NC | MUST | HC | missing |
| COMP-CA-005 | **Sponsor Attestation Checklist for an ANDS** | MUST | HC | missing |
| COMP-CA-006 | **SANDS** — attestation for generic PM updates aligned with CRP | SHOULD | HC | missing |
| COMP-CA-007 | **Master File** application form v3.0 + stylesheet (DMF/CEP refs in ANDS) | MUST | HC | partial (REQ-002 branches) |
| COMP-CA-008 | **Plain Language Labelling** timing / Q&A workflow for FR PM | SHOULD | HC | missing |
| COMP-CA-009 | **Non-eCTD electronic** folder structures (Vet ANDS zip templates) | COULD | HC | missing |
| COMP-CA-010 | **REP software_version** + product_name + company_id non-empty (I09) | MUST | HC | partial |
| COMP-CA-011 | CRP **three-category** rule + foreign CRP justification | MUST | HC | implemented |
| COMP-CA-012 | **Fee payment** evidence / mitigation forms linked to submission | SHOULD | HC | partial (fees module) |
| COMP-CA-013 | **Pediatric** / foreign regulatory info sections in Module 1 where applicable | COULD | HC | missing |
| COMP-CA-014 | HC recommendation: use **authenticated commercial eCTD tool** (not XML checker only) | MUST | HC guidance | partial |

### 2.8 Collaboration, workflow & QC (COMP-WF)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-WF-001 | Configurable **review & approval** workflow per document type | MUST | V7, V10, V11 | partial (REQ-076) |
| COMP-WF-002 | **Four-eyes principle** on publish/transmit actions | SHOULD | V3, V10 | partial (RBAC) |
| COMP-WF-003 | **Comments / annotations** on leaves and validation findings | MUST | V8, V7 | missing |
| COMP-WF-004 | **Task assignment** with email notifications and due dates | MUST | V7, V10 | missing |
| COMP-WF-005 | **QC checklist** workflow (publisher vs QC vs approver roles) | MUST | V8, V13 | partial |
| COMP-WF-006 | **Secure external sharing** with sponsor/CRO clients during build | SHOULD | V9, V13 | missing |
| COMP-WF-007 | **Optimistic locking** / conflict detection multi-user | MUST | all enterprise | missing (REQ-057) |
| COMP-WF-008 | **Submission readiness dashboard** READY/BLOCKED | SHOULD | our differentiator | implemented |
| COMP-WF-009 | **Audit export** for inspection (who published, who transmitted) | MUST | all | partial |

### 2.9 Integrations & ecosystem (COMP-INT)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-INT-001 | **DMS connectors** — SharePoint, Documentum, OpenText, Veeva Vault | SHOULD | V6, V11 | missing |
| COMP-INT-002 | **MasterControl** QMS — controlled PDF handoff to publisher | COULD | V11 | missing |
| COMP-INT-003 | **BIOVIA / Generis** integration | COULD | V6 | missing |
| COMP-INT-004 | **REST API** for dossier, validation, transmission status | MUST | SaaS expect | partial |
| COMP-WEB-005 | **Webhooks** on submission state changes | SHOULD | SaaS | missing |
| COMP-INT-006 | **drugTrack / RIM** product data → Module 1 auto-fill | COULD | V3+V1 | missing |
| COMP-INT-007 | Export to **LORENZ / EXTEDO** format for hybrid customers | COULD | interoperability | missing |

### 2.10 Archive, viewing & lifecycle (COMP-ARC)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-ARC-001 | **Submission archive viewer** (regulatory binder view) | MUST | V7 Archive, V6 Viewing | missing |
| COMP-ARC-002 | **Validation results archival** — ZIP attached to submission record after N days | COULD | V7 | missing |
| COMP-ARC-003 | Full **sequence history** with diff between sequences | SHOULD | V1, V6 | partial |
| COMP-ARC-004 | **Administrative / corrective** sequences (withdraw leaf, reorganize) | SHOULD | industry | missing (REQ-048) |
| COMP-ARC-005 | **Transfer of ownership** with history preservation | SHOULD | industry | missing (REQ-049) |
| COMP-ARC-006 | **Q&A response** sequence builder from NOD/NON | SHOULD | HC | partial (REQ-032) |
| COMP-ARC-007 | Ingest **HC lifecycle notices** (SDN, NOD, NOC, …) | SHOULD | HC | missing |
| COMP-ARC-008 | **Clarifax / clock-stop** UI with adjustable tiers | SHOULD | HC | partial |

### 2.11 eCTD v4 & future readiness (COMP-V4)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-V4-001 | **eCTD v4.0** compile/publish (EU draft; HC TIG draft) | COULD | V1, V6, V7, V8 | partial stub (REQ-041) |
| COMP-V4-002 | **Context of Use (CoU)** management | COULD | V7 | missing |
| COMP-V4-003 | **UUID / document reuse** across sequences (v4 model) | COULD | V7, V8 | partial (REQ-041) |
| COMP-V4-004 | **Hybrid v3.2.2 + v4** portfolio during transition (~2026–2028) | COULD | EXTEDO services | missing |
| COMP-V4-005 | Pin **HL7 RPS** / v4 CV packs as reference data | COULD | V7 | missing |

### 2.12 CRO & multi-client SaaS (COMP-CRO)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-CRO-001 | **Multi-sponsor workspace** — CRO publishes for many clients | MUST | V9, V13 | partial (multi-tenant) |
| COMP-CRO-002 | **Client portal** — sponsor reviews in-progress submission securely | MUST | V9, V13 | missing |
| COMP-CRO-003 | **White-label** branding per CRO partner | COULD | SaaS | missing |
| COMP-CRO-004 | **ML unstructured → structured** document intake (PDF/DOC → leaves) | COULD | V9 PhlexNeuron | missing |
| COMP-CRO-005 | **Per-sequence billing** / pass-through pricing for CROs | SHOULD | V1 ONE model | missing |
| COMP-CRO-006 | **Service handoff** — export to human publishing team when complex | COULD | V13, Certara | missing |

### 2.13 Compliance, validation & trust (COMP-GXP)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-GXP-001 | **21 CFR Part 11** features (audit trail, e-sign, authority checks) | MUST | V7, V8, V10 | partial |
| COMP-GXP-002 | **Vendor CSV package** — IQ/OQ/PQ per release | SHOULD | V8 Certara, V10 | missing |
| COMP-GXP-003 | **Validated installation** documentation per deployment | SHOULD | V1, V8 | missing |
| COMP-GXP-004 | **Functional + validation support** contract tier (LORENZ model) | COULD | V1 | missing |
| COMP-GXP-005 | **SOC 2 / ISO 27001** attestation for cloud | SHOULD | enterprise SaaS | missing |
| COMP-GXP-006 | **ALCOA+** e-records posture (value-add, labeled) | COULD | REQ-039 | partial |

### 2.14 Commercial & SaaS model (COMP-BIZ)

| ID | Requirement | Priority | Vendors | Our status |
|----|-------------|----------|---------|------------|
| COMP-BIZ-001 | **Transparent tier pricing** (public or self-serve quote) | MUST | eCTD 247, V1 ONE | missing |
| COMP-BIZ-002 | **Pay-per-sequence** option for low-volume generics | MUST | V1 docuBridge ONE | missing |
| COMP-BIZ-003 | **Monthly per-user SaaS** without capital license | MUST | eCTD 247, V10 | missing (SAAS-REQ-002 draft) |
| COMP-BIZ-004 | **Free eValidator Basic** for HC-only validation (competitive pressure) | COULD | V2 | n/a (we bundle) |
| COMP-BIZ-005 | **Trial / sandbox** tenant with sample ANDS dossier | MUST | SaaS | missing |
| COMP-BIZ-006 | **Professional onboarding** + first submission concierge | SHOULD | V13 EXTEDO | missing |
| COMP-BIZ-007 | **Training courses** (HC eCTD, CESG, ANDS content) | COULD | V3, V13 | missing |
| COMP-BIZ-008 | **Managed publishing services** upsell when self-serve blocked | COULD | Certara, EXTEDO | missing |
| COMP-BIZ-009 | **Maintenance-included spec updates** (2× yearly major releases) | SHOULD | V1 | partial (NFR-013) |

---

## 3. Vendor deep dives (loop notes)

### V1 — LORENZ docuBridge ecosystem

**What generics pay for:** predictable publishing, industry-trusted validation, lifecycle transparency, optional pay-per-sequence entry.

**Requirements they imply beyond our v1 gap doc:**

- Automatic **regulatory specification updates** without reinstall (COMP-BIZ-009).
- **Submission Repository Application Viewer** (Files + Outline) for QC (COMP-PUB-006).
- **Import eCTD** from other publishers (COMP-PUB-003).
- **Multi-format** publishing from one sequence (COMP-PUB-005).
- Tiered **commercial models** from single user to enterprise (COMP-BIZ-002/003).
- **Functional + validation support** tiers (COMP-GXP-004).
- Integration with **drugTrack** RIM and **Automator** for ESG (COMP-INT-006, COMP-TRN-002).
- **verifAI** cross-sequence content validation (COMP-CNT-002/003).

### V2 — LORENZ eValidator

**Benchmark for HC technical acceptance:** sponsors often validate with eValidator before transmit; HC explicitly encourages commercial tools.

**Gap vs us:** extended profiles, batch/server validation, CA Non-eCTD profile, PDF validation reports, webAccess UI, MD5/SHA256 proofreader — see COMP-VAL-*.

### V6 — EXTEDO

**Strengths:** visual assembly, broken-link engine, SPL (US), broad format coverage, DMS integrations, validator used by 35+ authorities.

**Gap vs us:** DMS connectors, incremental publish, parallel submission tracking, professional **document publishing services** (PDF fix at scale).

### V7 — Veeva Vault RIM

**Enterprise bar:** submission content plans, continuous publish/validate, gateway integration, registration tracking, correspondence — full **RIM suite** not just publisher.

**Gap vs us:** entire COMP-RIM block except partial portfolio/readiness.

### V8 — Certara GlobalSubmit

**Validation-first:** Live Validation (200+ checks), CrossCheck QC, integrated review annotations, 21 CFR Part 11, validated releases with training.

**Gap vs us:** COMP-VAL-003/010, COMP-WF-003, COMP-GXP-002.

### V9 — Phlexglobal

**CRO pattern:** cloud publishing + **ML document structuring** + secure client collaboration; service-provider multi-client economics.

**Gap vs us:** COMP-CRO-002/004, COMP-WF-006.

### V10 — Ennov / eCTD 247

**Affordable SaaS benchmark:** eCTD 247 Premium ~$1k/user/mo, unlimited submissions, built-in EDMS, DIA model, 21 CFR Part 11, drag-drop from EDM.

**Gap vs us:** COMP-BIZ-003, COMP-RIM-011, COMP-WF-004, built-in EDMS (or integrate), AI classification.

### V12 — Assyro AI

**Emerging bar:** decision-tree validation, cross-module logic, regulatory change monitoring, AI co-authoring — **beyond flat HC rules**.

**Gap vs us:** COMP-CNT-003/004/005 — strategic for “best ANDS app” narrative.

### V14 — Health Canada (mandatory overlay)

HC does not mandate a vendor but mandates **behaviour**. Critical additions not fully in v1 gap doc:

- Authenticated **commercial tool** expectation (COMP-CA-014).
- **Bilingual + XML PM** trajectory (COMP-CA-001/002).
- Module 1 **forms & attestations** (COMP-CA-004/005/006).
- **Validation before filing** culture (COMP-VAL-001).

---

## 4. Coverage summary

| Domain | Total COMP reqs | Implemented | Partial | Missing |
|--------|-----------------|-------------|---------|---------|
| COMP-PUB | 13 | 2 | 4 | 7 |
| COMP-VAL | 12 | 0 | 7 | 5 |
| COMP-CNT | 7 | 0 | 1 | 6 |
| COMP-PDF | 9 | 0 | 6 | 3 |
| COMP-TRN | 8 | 0 | 3 | 5 |
| COMP-RIM | 14 | 1 | 4 | 9 |
| COMP-CA | 14 | 2 | 4 | 8 |
| COMP-WF | 9 | 2 | 4 | 3 |
| COMP-INT | 7 | 0 | 1 | 6 |
| COMP-ARC | 8 | 0 | 3 | 5 |
| COMP-V4 | 5 | 0 | 1 | 4 |
| COMP-CRO | 6 | 0 | 1 | 5 |
| COMP-GXP | 6 | 0 | 2 | 4 |
| COMP-BIZ | 9 | 0 | 1 | 8 |
| **Total** | **127** | **7 (6%)** | **42 (33%)** | **78 (61%)** |

*Status reflects monolith + v1 vision doc baseline before v2 requirements.*

---

## 5. Priority backlog (industry MUST not in v1 gap doc)

Top 25 **industry MUST** requirements with **missing** or **weak** coverage:

1. COMP-CA-001 — Bilingual PM workflow  
2. COMP-CA-002 — XML Product Monograph  
3. COMP-CA-004 — Submission Certification Form  
4. COMP-CA-005 — ANDS Sponsor Attestation Checklist  
5. COMP-RIM-001 — Submission content plans  
6. COMP-VAL-003 — Live validation during assembly  
7. COMP-TRN-002 — Direct gateway submit from platform  
8. COMP-WF-003 — Comments on findings/leaves  
9. COMP-WF-004 — Task assignment + notifications  
10. COMP-ARC-001 — Submission archive viewer  
11. COMP-PUB-003 — Import external eCTD  
12. COMP-VAL-002 — CA Non-eCTD profile  
13. COMP-PDF-003 — PDF auto-remediation pipeline  
14. COMP-CRO-002 — Client review portal  
15. COMP-BIZ-002 — Pay-per-sequence tier  
16. COMP-BIZ-003 — Published SaaS pricing tiers  
17. COMP-BIZ-005 — Sandbox trial dossier  
18. COMP-INT-004 — Public REST API + docs  
19. COMP-GXP-001 — Part 11 feature completeness  
20. COMP-GXP-002 — Vendor CSV/IQ-OQ-PQ package  
21. COMP-RIM-003 — Registration tracking  
22. COMP-CA-003 — Annotated PM cross-ref builder  
23. COMP-VAL-010 — CrossCheck-style hyperlink QC  
24. COMP-PUB-006 — Post-publish sequence viewer  
25. COMP-CNT-003 — Content-level validation (AI or rules) — differentiator path  

---

## 6. References

- [LORENZ docuBridge](https://www.lorenz.cc/Solutions/docuBridge/)
- [LORENZ eValidator CA profiles](https://www.lorenz.cc/Solutions/eValidator-five/validation-profiles/)
- [EXTEDO Submission Management Hub](https://www.extedo.com/software/submission-management-hub)
- [Veeva Submissions Publishing](https://www.veeva.com/resources/veeva-submissions-publishing/)
- [Certara GlobalSubmit PUBLISH](https://www.certara.com/globalsubmit-ectd-submission-software/publish/)
- [Ennov Regulatory / eCTD 247](https://ectd247.com/)
- [Assyro eCTD comparison 2026](https://www.assyro.com/blog/best-ectd-submission-software)
- [IntuitionLabs eCTD comparison May 2026](https://intuitionlabs.ai/articles/ectd-software-comparison)
- [HC — Filing electronically](https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/filing-submissions-electronically.html)
- [HC — Module 1 placement table](https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/organization-document-placement-canadian-module-1.html)
- [HC — eCTD validation rules](https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/ectd/notice-validation-rules-regulatory-transactions-submitted-health-canada-electronic-common-technical-document-format-2016-12-1.html)

---

*Inventory feeds [`VISION-GAP-REQUIREMENTS.md`](VISION-GAP-REQUIREMENTS.md) v2.0 §10–§15.*
