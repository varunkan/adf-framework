# ANDS Submission Portal — Requirements Verification vs Health Canada

_Adversarial verification 2026-06-21: 8 RA auditors re-fetched live Health Canada documents/templates (9 agents, 141 fetches)._

## Verdict: **MATERIAL_ERRORS** — 48 claims confirmed, 34 corrections, 17 new gaps

Overall verdict: MATERIAL_ERRORS. Of seven audited areas, four were MINOR_CORRECTIONS (eCTD format & validation rules; ANDS content/BE; CESG transmission; full template inventory), one was SOLID (lifecycle/sequences/screening/acknowledgements), and three carried MATERIAL_ERRORS (REP identifiers, Fees & service standards, Privacy/residency/e-records). Any single MATERIAL_ERRORS area sets the consolidated verdict.

The core technical/regulatory backbone is well-founded and confirmed (~48 claims): eCTD validation rules v5.3 eff 2025-05-31 / notice 2025-01-10, categories A-I and specific rule IDs/severities, ca-regional.xml under m1/ca with root <hcsc_ectd> against CA Module 1 Schema v2.2, 0000/+1 sequencing (A07), MD5/index backbone, ICH v3.2.2; ANDS module-suppression logic (no Module 4, CS-BE path suppresses 2.4-2.7, full Module 3, three-category CRP rule); the FDA-ESG ride-along with no direct HC endpoint, WebTrader/AS2, X.509 cert, mandatory test round-trip, 10 GB ceiling, after-16:30 EST guidance; and the full screening/review lifecycle (45-day screening, 180-day ANDS review, clarifax 5/10/15, NOD 90/45-DIN, SDN/SAL/SRL/NOD/NON/NOC). REP template inventory, formats and immutable-filename rules are also sound.

The material errors are concentrated and fixable: (1) REQ-002 hardcodes the drug Dossier ID as ^m[0-9]{6}$ (m is medical devices; ANDS uses 'e' + 6-or-7 digits) AND inverts the 8-week rule (HC's 8 weeks is a MAXIMUM, not a minimum lead-time gate); (2) the on-time KPI is 100% for ANDS (Division 1 & 8), not 90%, and seed fee amounts are ~5 years / ~24% stale ($53,836 base vs $70,750 current), with the missing 25% fee-credit entitlement; (3) the privacy/compliance section converts GC-internal directives (Protected B in-Canada residency) and GMP/Annex-11 ALCOA+ best practice into HC mandates on a sponsor-side tool — HC's real requirements here are narrow (no file encryption/passwords/DRM; e-signatures accepted case-by-case under the HPFB policy). Other notable corrections: remove the fabricated 'Form V' term, place the CS-BE in Module 1.6 and resolve the 2.7.1-while-suppressing-2.4-2.7 contradiction, version the Cmax rule across the ICH M13A transition (eff 2025-12-27), relabel the ACK chain to NextGen and capture the Core ID, refresh REP template versions (RT now v5.1.0), and stop implying HC provides a fillable cover-letter template. 18 new gaps should become requirements — most importantly the QOS-CE (Module 2.3) template, the existing-dossier/DSTS-IA path, the 25% fee credit, M13A Cmax branching, CS-BE-in-1.6, a dedicated STF builder/validator, version-pinned schema/DTD/CV reference data, the REP XSL stylesheet, FDA ESG NextGen + Core-ID correlation, DRM/IRM and A02 checks, anchoring e-signatures to the HPFB policy, and a 'basis' field separating HC-mandates from value-add controls.

## Per-area verdicts

- **eCTD format & Validation Rules** — MINOR_CORRECTIONS — core claims (v5.3 eff 2025-05-31, notice 2025-01-10, categories A-I, rule IDs/severities, ca-regional.xml/Schema v2.2, 0000/+1 sequencing, MD5/index rules, ICH v3.2.2) all CONFIRMED in requirements.md; fixes needed: (1) label the v4.0 2026/2028 dates as industry estimates not HC-fixed (draft dates from 2019, original timeline lapsed); (2) drop the legacy 'index-m1.xml' alias that appears in the dossier (canonical is ca-regional.xml only); (3) the dossier's 150/200MB 'tool-config not a hard cap' hedge is wrong (A03a Warn / A03b Error are real HC rules — requirements.md already fixed this); plus add STF and version-pinned schema/DTD as reference data, and an A02 permission check.
- **ANDS content & bioequivalence — Module suppression (M4, 2.4-2.7 / CS-BE), Canadian Reference Product (CRP)/comparator rules, "Form V" currency, AUC/Cmax acceptance criteria** — MINOR_CORRECTIONS — core ANDS module-suppression logic (Module 4 not required; CS-BE path suppresses 2.4-2.7; full Module 3; CRP three-category rule) is CONFIRMED, but four fixes are needed: (1) remove all 'Form V' references — it is not a Health Canada term (CS-BE supersedes the PCERT BE module, not 'Form V'); (2) CS-BE electronic copy goes in Module 1.6, and emitting a 2.7.1 while suppressing 2.4-2.7 is contradictory; (3) the Cmax acceptance rule is a versioned moving target — point-estimate pre-M13A vs full 90% CI under ICH M13A (effective 2025-12-27); (4) CS-BE and the comparative-BA CTD guidance are still DRAFT, not final.
- **CESG transmission — the FDA-ESG ride-along claim (no direct HC endpoint), FDA ESG onboarding (WebTrader/AS2, X.509 cert, mandatory test round-trip, designate HC as recipient), ~10 GB per-transaction limit, after-16:30 EST guidance, and the acknowledgement chain** — MINOR_CORRECTIONS — the central FDA-ESG ride-along claim, no-direct-HC-endpoint, WebTrader/AS2, X.509 cert, mandatory test round-trip, HC-as-recipient, the 10 GB ceiling, and the after-16:30/4:30 PM EST 5-10 GB guidance are all CONFIRMED against live HC sources; correct the acknowledgement-chain labeling (HC's three artifacts are MDN + FDA Acknowledgement + HC Acknowledgement Receipt; the MDN!=ACK1 framing is wrong under FDA ESG NextGen), add the ESG NextGen (April 2025) context, capture the Core ID, and source-or-rescope REQ-027.
- **REP identifiers & templates (Company CO / Regulatory Transaction RT / Product Information PI templates; Dossier ID request & 8-week rule; REP XML flow into Module 1)** — MATERIAL_ERRORS — template inventory/formats/versions are SOLID (CO 2025-06-03, RT 2025-09-10, PI 2024-02-12, stylesheet 2025-09-10, all web-form-to-XML, immutable filenames), but two requirement-level errors must be fixed: (1) REQ-002 hardcodes the drug Dossier ID as ^m[0-9]{6}$ — wrong; ANDS uses prefix 'e' and IDs are 6-or-7 digits by activity type ('m' is medical devices, 'f'+7 is non-eCTD Master Files); (2) REQ-002 inverts the 8-week rule (HC says request NO EARLIER than 8 weeks before filing — a maximum, not a minimum lead-time gate). Plus: AI template and the '1.04' placement are medical-device-only and should not be applied to a drug ANDS; missing existing-dossier/DSTS-IA path; missing clinical-trial & Master File request branches; Company-ID-as-5-digits is unverified and likely too strict.
- **Lifecycle, sequences, screening & acknowledgements (ANDS submission portal)** — SOLID — lifecycle, sequence, screening, clarifax/NOD/NON and acknowledgement claims all verified correct against live HC sources; only minor corrections (NOD-W/NON-W notation, type-dependent Inactive-45/90, adjustable clarifax windows, guidance pinned to 2025-10-01 edition).
- **Fees & service standards** — MATERIAL_ERRORS
- **Privacy, residency, e-records & signatures (Health Canada ANDS submission portal)** — MATERIAL_ERRORS — the requirements conflate Government-of-Canada internal directives and GMP/Annex-11 best practice with actual Health Canada obligations on a sponsor-side tool; residency "Protected B in Canada" and ALCOA+/Annex-11 e-signatures are imposed as HC mandates when HC does not require them. Real HC requirements in this area are narrow (no file encryption/passwords; e-sig accepted case-by-case under HPFB policy). Recommend reclassifying overstated items as value-add controls.
- **Full forms & templates inventory — every fillable form, template, schema, DTD, stylesheet, and controlled-vocabulary file Health Canada provides that an ANDS submission portal must generate, fill, or validate against** — MINOR_CORRECTIONS — core template/schema inventory is sound and correctly handled, but REP template versions are stale (RT now v5.1.0/2025-09-10, CO v5.0.0), the cover letter is wrongly implied to be an HC fillable template, and the requirements omit the QOS-CE template, the REP XSL stylesheet package, the ICH util DTD/stylesheet, and the explicit Module 1 controlled-vocabulary files.

## Corrections

### [HIGH] REQ-002 hardcodes the drug Dossier ID validator as ^m[0-9]{6}$. The 'm' prefix is the MEDICAL-DEVICE convention, not the pharmaceutical/ANDS convention.

**Fix:** ANDS (pharmaceutical/biologic eCTD) Dossier IDs use prefix 'e'; IDs are a lowercase letter + 6 OR 7 digits depending on activity type (e=pharma/biologic & eCTD Master Files, f+7=non-eCTD Master Files, m=medical device). Replace ^m[0-9]{6}$ with a prefix-by-type + 6-or-7-digit pattern (e.g. ^[a-z][0-9]{6,7}$) defaulting an ANDS to 'e'. The dossier's own ANDS-section example (e123456/e004567) contradicts its REP-section 'm-for-drugs' statement; the 'm' statement is the error.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/filing-submissions-electronically.html

### [HIGH] REQ-002 INVERTS the 8-week dossier-ID rule. It enforces an 8-week lead-time GATE and flags when the filing date is LESS than 8 weeks away, treating 8 weeks as a minimum lead time.

**Fix:** HC's rule is a MAXIMUM: a dossier-ID request should be placed NO MORE than 8 weeks before filing (don't request too early). The portal should warn when a request is placed MORE than 8 weeks ahead, not less. The acceptance criterion 'first-filing date less than 8 weeks away -> flag lead-time violation' is backwards and must be rewritten.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/filing-submissions-electronically/pharmaceutical-dossier-template.html

### [HIGH] REQ-034 specifies a 90% on-time service-standard KPI for ANDS. For Division 1 & 8 drug submissions (NDS/ANDS/SNDS/SANDS) HC's published target is 100% to first decision; 90% applies to other classes (Notifiable Changes, CTAs).

**Fix:** Measure ANDS against a 100% on-time commitment, not 90%. Retain 90% only where the portal also tracks Notifiable Changes/CTAs. Also surface the 25% fee-credit entitlement when HC misses the standard.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions-applications/performance-standards.html

### [HIGH] REQ-035/dossier line 250 uses $53,836 CAD as the 'current' ANDS comparative-studies fee. That is the FY2020-21 base value from SOR/2019-124 Schedule 1, ~24% low.

**Fix:** Treat $53,836 as a historical CPI-anchor seed only. Current ANDS comparative-studies fee = $70,750 (FY2025-26, eff. Apr 1 2025) and $71,953 (FY2026-27, eff. Apr 1 2026). REQ-035's data-driven April-1 CPI escalation architecture is sound; refresh the seed/fixture values so no UI/test displays the stale figure as current.  
_Source:_ https://qualitysmartsolutions.com/news/what-you-need-to-know-about-health-canada-fees-in-2026/

### [HIGH] Dossier line 59 claims the CS-BE supersedes a legacy 'Form V' and that 'Form V' is current comparative-bioavailability terminology.

**Fix:** 'Form V' is not a Health Canada term (zero hits in current or archived HC guidance). The CS-BE supersedes the Bioequivalence Studies module of the PCERT (Preclinical and Clinical Evaluation Report Template), not 'Form V'. Remove all 'Form V' references; they are fabricated/non-Canadian. Requirements.md does not propagate this, so flag the dossier only.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/templates/notice-draft-comprehensive-summary-bioequivalence.html

### [HIGH] REQ (line 100/106) routes CS-BE output to Module 2.7.1, while REQ (line 54) says the CS-BE path SUPPRESSES Modules 2.4-2.7. 2.7.1 is inside the suppressed block — internally contradictory. The mandated Module 1.6 electronic CS-BE copy is also missing.

**Fix:** For a BE-only ANDS: place the CS-BE electronic copy in Module 1.6, place full study reports in Module 5.3.1.2, and do NOT auto-generate a 2.7.1 (2.4-2.7 suppressed). Generate a 2.7.1 only on the full-2.7 path when other safety/efficacy studies are present. The eCTD assembler must add the m1 section 1.6 placement.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/templates/notice-draft-comprehensive-summary-bioequivalence.html

### [HIGH] REQ (line 100/105) hardcodes 'AUC/Cmax 90% CI'. Pre-M13A HC required only the Cmax POINT ESTIMATE (relative mean) within 80.0-125.0% and did NOT require a 90% CI for Cmax. Limits are written 80.0-125.0% (one decimal) in the standards guidance.

**Fix:** Under ICH M13A (effective 2025-12-27, IR solid oral) the full 90% CI for Cmax must be within 80.00-125.00%. Branch Cmax validation: point-estimate (legacy/non-IR) vs 90% CI (M13A IR). Pin the BE ruleset by submission date and dosage-form class; do not hardcode a single Cmax rule.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/announcements/notice-ich-m13a-bioequivalence-immediate-release-solid-oral-dosage-forms.html

### [HIGH] Requirements impose 'Protected B data resident in Canada' (pin all stores/processing/caches/logs/backups to Canadian regions; no cross-border replication) as a Health Canada mandate, citing the GC 'Direction for Electronic Data Residency' (BT22-210/2018E).

**Fix:** That Direction binds GC departments/agencies, not a private sponsor's SaaS. HC imposes NO data-residency or Protected B classification on a sponsor's submission-prep tool. Reclassify in-Canada/Protected B residency as a configurable VALUE-ADD control. Residency becomes a real obligation only via the sponsor's own contracts, provincial health-privacy law where PHI is involved, or procurement by/for a GC body. Drop the 'SHALL ... 100% of Protected B data flows resident in Canada' HC-compliance framing.  
_Source:_ https://publications.gc.ca/site/eng/9.856443/publication.html

### [HIGH] REQ-039/NFR-003 impose Annex-11/ALCOA+ e-signature, tamper-evident manifest, QA audit-trail sign-off gate and CSV (IQ/OQ/PQ) as Health Canada requirements on the submission portal.

**Fix:** HC's real rule: e-signatures on submission content are accepted case-by-case under the HPFB Electronic Signatures Policy (obtainable via hc.cesg-pcde.sc@canada.ca) — a permission, not a mandated Part-11/Annex-11/ALCOA+ control set. ALCOA+/Annex-11/CSV apply to GMP/GxP source records and inspected establishments, not to a sponsor's eCTD assembly tool. Re-label these MUSTs as value-add/best-practice. Add a 'basis' field per requirement (HC-mandate | GC-direction | provincial-privacy | PIPEDA | GMP-best-practice | value-add).  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/common-electronic-submissions-gateway/frequently-asked-questions.html

### [MED] REQ-035/040 models escalation as one global annual CPI factor.

**Fix:** A subset of fees (DMF, Certificate of Pharmaceutical Product, Certificate of Supplemental Protection, Human Drug Dealer's Licence) escalates on a 2% ministerial-authority basis (eff. Apr 1 2026), not the CPI rate. The CPI table must be keyed per fee grouping with a per-grouping escalation basis, not a single global rate.  
_Source:_ https://laws-lois.justice.gc.ca/eng/regulations/SOR-2019-124/FullText.html

### [MED] REQ-037 tracks the recurring per-DIN annual right-to-sell fee generically (amount + anniversary) but omits the by-drug-type differentiation and the statutory due date.

**Fix:** Key the amount by drug type (prescription ~$5,531 / non-prescription ~$3,334 / disinfectant ~$1,730 FY2025-26; ~$5,626 / $3,391 / $1,760 FY2026-27; biocide $1,535 base) and pin the statutory due date of October 1. The dossier omitted both.  
_Source:_ https://laws-lois.justice.gc.ca/eng/regulations/SOR-2019-124/FullText.html

### [MED] The dossier treats the CS-BE path as settled/final.

**Fix:** Both the CS-BE template and the 'Preparation of Comparative Bioavailability Information in CTD Format' guidance remain DRAFT (dated 2004-05-18). Add a guidance-version/draft-status flag so the portal adapts when they are finalized (likely alongside M13A); do not present the CS-BE path as a finalized hard gate.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/common-technical-document/draft-guidance-industry-preparation-comparative-bioavailability-information-drug-submissions-format.html

### [MED] The compliance section cites HC filing-electronically guidance and the Mandatory-REP notice as the basis for residency, Protected B, Annex-11 e-signature, and PIPEDA requirements. Those HC pages say nothing about any of these.

**Fix:** Re-attribute: HC submission guidance supports ONLY no file encryption/passwords (CESG FAQ) and case-by-case e-signature acceptance (HPFB policy). Residency/Protected B = GC TBS direction; PIPEDA/breach = OPC (with provincial overlays); ALCOA+/Annex-11/CSV = GMP/GxP best practice.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/regulatory-enrolment-process/notice.html

### [MED] Requirements assert PIPEDA as THE exclusively governing private-sector privacy law.

**Fix:** PIPEDA breach-management requirements (RROSH reporting, OPC notify, 24-month record) are genuine — keep them. But for activity wholly within AB/BC/QC the substantially-similar provincial PIPA may apply instead, and where personal HEALTH information is handled, provincial health-privacy law (e.g. Ontario PHIPA) may govern. Treat PIPEDA as the default/baseline with a configurable provincial overlay. ANDS content has limited PHI, so the privacy surface is smaller than implied.  
_Source:_ https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/r_o_p/prov-pipeda/

### [MED] The dossier labels the chain MDN -> ACK1(FDA) -> ACK2(HC) and frames the MDN as a distinct pre-ACK1 layer. Under FDA ESG NextGen, for AS2 the MDN IS ACK1; ACK1=uploaded into ESG, ACK2=transmitted to Center, ACK3=final FDA ack. The 'MDN != ACK1' framing conflates two numbering schemes.

**Fix:** Model HC's three actual artifacts as the canonical chain: (1) MDN (AS2/transport receipt; under NextGen this is ACK1 for AS2), (2) FDA Acknowledgement (ESG accepted / transmitted-to-Center, carries Message ID + Core ID), (3) Health Canada Acknowledgement Receipt (carries Core ID = true HC delivery). Keep 'success only on the HC Acknowledgement Receipt.' REQ-028's state machine shape is fine; relabel FDA_ACK as 'FDA Acknowledgement' (not 'ACK1') and capture the Core ID. The 3-item count and core delivery rule are correct.  
_Source:_ https://www.hc-sc.gc.ca/dhp-mps/prodpharma/applic-demande/guide-ld/cesg-pcde/faq-longdesc2-eng.php

### [MED] Neither the dossier nor the requirements mention FDA ESG NextGen (deployed April 2025). The integration is implicitly written against legacy ESG (endpoints, registration portal, ACK labeling).

**Fix:** WebTrader/AS2, X.509 certs, test-before-prod and HC-recipient routing persist, but the registration portal, API surface, and ACK model (ACK1/2/3 + Core ID) are the NextGen ones. Pin the ESG environment version (the way REQ-040/056 pin the validation ruleset) and target the NextGen model in REQ-003/028/046.  
_Source:_ https://www.fda.gov/industry/electronic-submissions-gateway-next-generation-esg-nextgen

### [MED] The dossier's REP template versions are behind the live portal (RT cited as 5.0.0/2025-03-26).

**Fix:** Live current versions: Company (CO) v5.0.0 (2025-06-03), Regulatory Transaction (RT) v5.1.0 (2025-09-10, superseding the dossier's 5.0.0), Product Information (PI) 2024-02-12, REP XML stylesheet zip 2025-09-10. The 2025 generation jumped from 4.4.x to 5.x. Pin REP template version as tracked reference data with the 5.x generation as the floor.  
_Source:_ https://health-products.canada.ca/rep-pir/version_history.html

### [MED] REQ-001/009/043/044 imply HC provides a cover-letter template the portal fills.

**Fix:** The cover letter is sponsor-AUTHORED, placed under the m1-0-1-cover-letter leaf (heading 1.0). HC provides only the placement slot, no cover-letter .docx/.dotx. The portal must generate a cover letter from its OWN template and auto-populate the Dossier ID (REQ-043's flow is right); state this explicitly so engineers don't hunt for a non-existent HC form.  
_Source:_ https://intuitionlabs.ai/articles/health-canada-ectd-submission-guide

### [MED] The research dossier conflated the Application Information (AI) template as a drug REP template and applied the 'final RT + AI XML in folder 1.04/1.05' placement to the ANDS path.

**Fix:** The AI template and the 1.04/1.05 placement are MEDICAL-DEVICE / IMDRF ToC, not drug eCTD. For an ANDS, REP transaction metadata lands in m1/ca/ca-regional.xml (CA Module 1 Schema v2.2). Scope AI and the 1.04 folder to the device path only; REQ-006's generic 'place RT/PI in Module 1' should specify the drug eCTD location.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/medical-devices/application-information/guidance-documents/regulatory-enrolment-process/process.html

### [MED] The research dossier hardcodes Company ID as exactly 5 numeric digits (implied in REQ-001's pattern), but the only concrete sample filename token (final-com-K18276-...) is a 6-char alphanumeric.

**Fix:** Do NOT hardcode Company ID as 5 numeric digits; a 5-digit numeric validator would reject HC's own IDs. Treat it as an HC-assigned opaque token and validate loosely, or confirm the exact format from the request-only REP Guidance PDF before constraining it.  
_Source:_ https://health-products.canada.ca/rep-pir/index.html

### [LOW] Dossier line 67 says '10 days processing + 25 days screening + 180 review (~215 total)'; lines 256/268 say ~10-day processing + 45-day screening. The two figures contradict (10+45+180=235; 10+25+180=215).

**Fix:** Standardize on the 45-day screening target (matches REQ-030/031 SDN 45-day window). The line-67 '25 days / ~215 total' phrasing is the stale/erroneous one. Dossier-internal defect, not a requirements defect, but clean it up so tests don't encode the wrong number.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions-applications/processing-screening.html

### [LOW] The CESG-section audit could not find a primary HC source (within its three re-fetched CESG URLs) for the one-transaction-at-a-time-per-dossier rule, flagging the rationale as overstated.

**Fix:** NOTE: the lifecycle-area audit DID confirm this against the live CESG FAQ ('Sponsors should ensure they have received the Health Canada acknowledgement for one transaction prior to sending a subsequent transaction'; out-of-order = A07). So REQ-027 is well-founded — just cite the CESG FAQ explicitly in REQ-027's rationale to close the sourcing gap the first audit raised.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/common-electronic-submissions-gateway/frequently-asked-questions.html

### [LOW] REQ-025 hard-blocks transactions above 10 GB.

**Fix:** HC says over-limit transactions 'should continue to be submitted on media' (the residual path, not framed as a hard prohibition). REQ-025's hard block is defensible but slightly stricter than HC's 'should'; consider phrasing as 'route to media' rather than an outright block.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/common-electronic-submissions-gateway/frequently-asked-questions.html

### [LOW] The dossier presents the v4.0 voluntary ~2026 / mandatory ~2028 dates as if HC-published.

**Fix:** These are industry-roadmap estimates, not firm HC commitments. The HC draft CA Module 1 TIG for eCTD v4.0 first went to consultation in June 2019; its original timeline (pilot 2023, voluntary 2024, mandatory 2027) has already lapsed and no HC notice fixes a binding date as of 2026-06. REQ-046 correctly hedges '~2026/~2028' as COULD-priority readiness work; just don't present the dates as HC-fixed in the dossier.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/announcements/notice-draft-guidance-canadian-module-1-technical-implementation-guide-ectd-v4-format.html

### [LOW] The dossier CESG section (line 119) lists 'index-m1.xml' as an alias for the CA Module 1 backbone.

**Fix:** Canonical HC name is ca-regional.xml ONLY; 'index-m1.xml' does not appear in official HC guidance (a legacy/incorrect label that also leaked into one IntuitionLabs guide). Requirements.md REQ-019 correctly uses ca-regional.xml and does not propagate the error — flag the dossier inconsistency only.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/ectd/canadian-module-1-schema-version-2-2.html

### [LOW] The dossier eCTD section omitted A03a/A03b and hedged that the 150/200MB PDF limits are commercial-validator 'tool-config, not a hard HC byte cap'.

**Fix:** Wrong: A03a (Warn 150-200MB) and A03b (Error >=200MB) are real published HC validation rules, not tool-config. Requirements.md already fixed this (REQ at line 165). Flag the dossier hedge only.  
_Source:_ https://intuitionlabs.ai/articles/ectd-validation-errors-guide

### [LOW] One secondary source (regulatoryaffairsnews) described 'critical/major/minor' severities.

**Fix:** HC's published model is two-tier Error/Warning (not FDA's three-tier High/Medium/Low and not critical/major/minor). The 'critical/major/minor' framing is that source's editorial gloss; use Error/Warning. Requirements are consistent with Error/Warning.  
_Source:_ https://intuitionlabs.ai/articles/ectd-validation-errors-guide

### [LOW] Dossier CESG section (line 120) states ~90 total validation rules in categories A-I.

**Fix:** The A-I category grouping is confirmed; the precise count (~90) could not be confirmed from an accessible HC source (the canonical Validation Rules spreadsheet was 403). Treat '~90' as approximate and read the live spreadsheet at build time.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/ectd/notice-validation-rules-regulatory-transactions-submitted-health-canada-electronic-common-technical-document-format-2016-12-1.html

### [LOW] REQ-014 asserts root <hcsc_ectd> with <m1-administrative-and-product-information>, but the dossier's REP section instead references an <ectd-regulatory-transaction-information> element; the XSD could not be retrieved to verify.

**Fix:** Download and pin the real Canadian Module 1 Schema v2.2 XSD (dated 2012-07-06) and generate against it rather than against element names asserted in the docs. The <hcsc_ectd> root is corroborated by the Schema v2.2 notice; resolve the dossier's internal element-name inconsistency against the actual XSD.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/ectd/canadian-module-1-schema-version-2-2.html

### [LOW] REQ-033 writes withdrawal statuses as 'NOD/W' and 'NON/W'.

**Fix:** HC's exact acronyms are NOD-W (Notice of Deficiency - Withdrawal) and NON-W (Notice of Non-Compliance - Withdrawal), with a hyphen. Align controlled-vocabulary/status labels to HC's exact terminology.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions-applications/review.html

### [LOW] REQ-030 flatly ties SDN to 'Inactive 45'. Correct for screening, but for NOD/NON the Inactive status is type-dependent.

**Fix:** HC sets 'Inactive 45' OR 'Inactive 90' on NOD/NON depending on submission/application type. The DSTS state machine must derive the NOD/NON Inactive window from submission type, not hardcode 45.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions-applications/review.html

### [LOW] REQ-031/051 model fixed 5/10/15-day clarifax tiers.

**Fix:** HC states the 2-15 day tiers are 'guidelines only ... can be adjusted longer or shorter' and special cases exist (clinical-trial screening clarifax = 2 days; multi-clarifax Division 1 changes cut to 5 days). Treat the tier as a default that is overridable per HC-agreed window per notice; don't hardcode 5/10/15.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions-applications/review.html

### [LOW] REQ-030/031 and the dossier do not pin the management-of-drug-submissions guidance edition.

**Fix:** The guidance was re-issued effective 2025-10-01 (day counts carried through unchanged). Pin the reference-data layer (REQ-040/NFR-013) to the 2025-10-01 edition and cite the version/effective date, consistent with the version-transition handling REQ-056 already requires for validation rulesets.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions-applications.html

### [LOW] Dossier line 252 example component fees (packaging/sterilization $7,888; expiry-date extension $5,930; concurrent use of two drugs $5,930, eff Apr 1 2026) could not be reconfirmed.

**Fix:** Re-verify these three amounts against the live April-1-2026 HC fee table / Canada Gazette before seeding; do not treat them as authoritative on the dossier's word alone.  
_Source:_ https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/fees/fees-review-drug-submissions-applications/applicable-fees.html

## New gaps -> requirements

- No requirement covers the QOS-CE (Quality Overall Summary — Chemical Entities) template for Module 2.3. REQ-004 keeps 2.3 QOS 'required' and REQ-044 has a generic checklist, but nothing makes the portal generate/fill/validate the actual HC QOS-CE template the way REQ-008 does for CS-BE. Module 3 + the 2.3 QOS is mandatory for an ANDS.
  - -> Add a requirement for the portal to generate/fill/validate the HC QOS-CE template for Module 2.3 (parallel to REQ-008's CS-BE handling); a missing/incorrect QOS is a screening-deficiency risk.
- No 'existing dossier ID / DSTS-IA retrieval' path. For follow-up sequences on an existing dossier in the same format, HC says no new request is needed and existing IDs come from DSTS-IA. An ANDS portal mostly files follow-up sequences (responses, SANDS), so forcing a new request each time is wrong and would gate the workflow via the (also-inverted) 8-week rule.
  - -> Add an 'existing dossier ID' path to REQ-002: skip the request and optionally look up the ID via DSTS-IA (contact client.information@hc-sc.gc.ca) for continuing sequences in the same format.
- Dossier-ID request workflow is missing branches. HC publishes SEPARATE request forms for pharmaceutical/biologic, pharmaceutical clinical-trial, biologic clinical-trial, veterinary, biocide, medical device, AND Master Files. REQ-002 lists only four.
  - -> Expand REQ-002 to branch across all HC dossier-ID request forms including pharmaceutical/biologic clinical-trial and Master Files; a referenced DMF/Master File needs its own e+6 (eCTD) or f+7 (non-eCTD) ID requested on its own form.
- No requirement for the 25% fee credit when HC misses a service standard. SOR/2019-124 credits the sponsor 25% of the fee paid if the submission isn't reviewed within the performance standard. The portal already tracks days-elapsed-vs-target (REQ-034) and pays the fee — concrete sponsor value entirely absent.
  - -> Add a requirement to detect a missed performance standard and surface/trigger the statutory 25% fee credit.
- The ICH M13A transition (effective 2025-12-27) is not modeled. The CS-BE/BE validator must be versioned by submission date and dosage-form class and branch Cmax between point-estimate (legacy/non-IR) and full 90% CI (M13A IR). A single hardcoded Cmax rule will wrongly fail/accept products.
  - -> Add a requirement to version the BE acceptance ruleset by date + dosage-form class and branch Cmax validation per M13A.
- CS-BE electronic-copy placement in Module 1.6 is missing. REQ routes CS-BE output to 2.7.1 and study links to 5.3.1.2 but omits the mandated m1 section 1.6 electronic CS-BE copy.
  - -> Require the eCTD assembler to place the CS-BE electronic copy in Module 1.6.
- No dedicated STF (Study Tagging File) builder/validator requirement. REQ-049 mentions STF presence under cross-document consistency, but STF is its own HC eCTD validation category with its own rules; missing/incorrect STFs are a validation finding wherever Module 4/5 study data appears.
  - -> Add a dedicated STF generation/validation requirement for transactions containing study data (low-frequency for ANDS but required where Module 5 BE study reports or any study data appear).
- The Canadian Module 1 Schema v2.2 and the ICH eCTD v3.2.2 DTD are not first-class version-pinned reference data. REQ-040 lists ruleset versions and the Module 1 placement table but not the schema version (v2.2) or DTD version (3.2.2). The schema can rev independently of the validation ruleset.
  - -> Add the CA Module 1 Schema version (v2.2) and the ICH eCTD DTD version (3.2.2) as independently version-pinned, updatable reference-data artifacts loaded as data.
- The REP XML stylesheet package (pharmabio_stylesheets_en.zip, 2025-09-10) is not referenced anywhere. HC ships the XSL stylesheets to render REP XML for human review; without a version-matched stylesheet the portal can't reliably preview what HC will display.
  - -> Add a requirement to bundle/track the version-matched REP XML stylesheet and render generated REP XML for human review before filing (supports the REQ-024 preview acceptance criterion).
- The util/ folder DTD and stylesheet are under-specified. REQ-014 generates index.xml + ca-regional.xml + util/ but never names the ICH eCTD DTD/XSL the util folder must carry, nor requires validating index.xml against HC's published DTD (it names only the regional XSD).
  - -> Require the portal to carry the exact HC-published ICH eCTD DTD + XSL in util/ and validate index.xml against the DTD, not just the regional XSD (A06a/H08-class rejections include missing/misnamed/schema-invalid backbones).
- No requirement inventories the Module 1 controlled-vocabulary / enumeration files (submission/activity types, dosage form, route, etc.) as HC-published, schema-version-keyed artifacts. REQ-005/022/040 reference 'HC controlled vocabulary' abstractly.
  - -> Require the portal to ingest the actual HC-published CV/enumeration files keyed to the Module 1 schema version (rules I08/H08 reject metadata values not in HC's controlled vocabulary), not a hand-maintained list.
- Capture/store the Core ID as the correlation key. The HC Acknowledgement Receipt (true delivery) carries the Core ID; the FDA Acknowledgement carries Message ID + Core ID. REQ-028/029/046 name states but not the correlation keys needed to tie a SENT transaction to its acknowledgements, HC receipt, and the later emailed eCTD Validation Report.
  - -> Require the ack-reconciliation logic to match on Message ID / Core ID and store the Core ID as the stable correlation key (needed for REQ-045/046 duplicate-send protection and REQ-058 media-path reconciliation).
- FDA ESG NextGen (April 2025) is not modeled — the registration portal, ACK1/2/3 + Core ID model, and NextGen AS2/WebTrader guides. The transmission integration is implicitly written against legacy ESG.
  - -> Require the transmission integration to target FDA ESG NextGen (registration portal, NextGen ACK model, NextGen AS2/WebTrader guides) and to pin the ESG environment version like the validation ruleset.
- No requirement surfaces/operationalizes the actual HPFB Electronic Signatures Policy as the governing artifact, nor a workflow to obtain/confirm HC acceptance of a given e-signature approach. The requirements build an Annex-11 control set from best practice but never anchor to HC's case-by-case policy.
  - -> Add a requirement to anchor e-signature handling to the HPFB Electronic Signatures Policy (request via hc.cesg-pcde.sc@canada.ca) with a workflow to confirm HC acceptance case-by-case.
- No requirement distinguishes HC-MANDATED controls from VALUE-ADD/best-practice controls. Residency/Protected B, ALCOA+/Annex-11 e-sig, CSV (IQ/OQ/PQ), DR/RPO/RTO and retention are all presented as 'MUST' with HC framing, overstating regulatory obligation.
  - -> Add a 'basis' field per compliance requirement (HC-mandate | GC-direction | provincial-privacy | PIPEDA | GMP-best-practice | value-add) so sponsors can scope cost/risk and auditors aren't misled.
- Missing the explicit HC prohibition on non-password security settings (DRM/IRM, restricted access, rights management). The requirements cover encryption/passwords/Track-Changes but not DRM/IRM/restricted-access, which HC explicitly blocks — a transaction with these set fails at HC even if it passes the portal's PDF-conformance gate.
  - -> Add a requirement to detect and block DRM/IRM/restricted-access/rights-management settings on submission files (alongside the existing A09 encryption/password check).
- A02 (File and Folder Security / readability) is only partially reflected. REQ-009 covers relative-links/no-external-hyperlinks and REQ-008 covers encryption/password (A09), but no explicit requirement mirrors A02 file/folder access-permission readability checks distinct from encryption.
  - -> Add a requirement mirroring HC rule A02 (file/folder permission/readability) as a distinct validation check separate from PDF encryption (A09).

## Health Canada template / form inventory

| Template/Form | Format | Covered? | URL |
|---|---|---|---|
| eCTD Validation Rules document/spreadsheet (v5.3, effective 2025-05-31) | PDF/spreadsheet; portal mirrors as versioned rule data; HC validates every transaction against it | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/ectd/notice-validation-rules-regulatory-transactions-submitted-health-canada-electronic-common-technical-document-format-2016-12-1.html |
| Canadian Module 1 Schema v2.2 (XSD) + ca-regional.xml backbone | XSD schema (dated 2012-07-06); ca-regional.xml in m1/ca validates against it, root <hcsc_ectd> | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/ectd/canadian-module-1-schema-version-2-2.html |
| ICH eCTD util folder — DTD + XSL stylesheet + index.xml + index-md5.txt (ICH v3.2.2) | ICH backbone XML + MD5 text file + DTD/XSL in util/ | NO | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/filing-submissions-electronically.html |
| Module 1 controlled-vocabulary / enumeration files (submission/activity type, dosage form, route) | HC-published CV/enumeration files keyed to the Module 1 schema version | NO | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/organization-document-placement-canadian-module-1.html |
| Organization and document placement table (CA Module 1 headings/leaves, incl. m1-0-1-cover-letter) | HTML heading/leaf reference table; portal drives the Module 1 tree from it as data | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/organization-document-placement-canadian-module-1.html |
| Draft Canadian Module 1 TIG for eCTD v4.0 (HL7-RPS) | PDF draft guidance + future XSD/Genericode CVs; readiness-only (COULD-priority) | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/public-involvement-consultations/drug-products/draft-guidance-canadian-module-1-technical-implementation-guide-ectd-v4-format/document.html |
| Study Tagging Files (STF) for Module 4/5 study leaves | STF XML accompanying clinical/nonclinical study documents | NO | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/filing-submissions-electronically.html |
| REP Company (CO) template — v5.0.0 (2025-06-03) | Fillable web form -> REP CO XML (filename final-com-<COMPANYID>-<YYYY-MM-DD>-<HHMM>.xml, immutable) | yes | https://health-products.canada.ca/rep-pir/company/en/company.html |
| REP Regulatory Transaction (RT) template — v5.1.0 (2025-09-10) | Fillable web form -> REP RT XML (immutable filename); mandatory with every transaction | yes | https://health-products.canada.ca/rep-pir/transaction/en/regulatory-transaction.html |
| REP Product Information (PI) template — 2024-02-12 | Fillable web form -> REP PI XML; required for a transaction subset only | yes | https://health-products.canada.ca/rep-pir/v44/product/product.html |
| REP XML stylesheet package (pharmabio_stylesheets_en.zip, 2025-09-10) | ZIP of XSL stylesheets to render REP XML for human-readable review | NO | https://health-products.canada.ca/rep-pir/stylesheet/pharmabio_stylesheets_en.zip |
| REP Application Information (AI) template — MEDICAL-DEVICE/IMDRF only | REP XML; paired with RT in device IMDRF ToC (folder 1.04); NOT a drug-eCTD template | NO | https://www.canada.ca/en/health-canada/services/drugs-health-products/medical-devices/application-information/guidance-documents/regulatory-enrolment-process/process.html |
| Dossier ID request form — Human drugs (pharmaceutical/biologic) | Document template emailed to HC (NOT a REP web template); returns the e+6/7-digit Dossier ID | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/filing-submissions-electronically/pharmaceutical-dossier-template.html |
| Dossier ID request forms — veterinary, biocide, medical device | Distinct HC document templates per product line | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/filing-submissions-electronically.html |
| Dossier ID request forms — pharmaceutical/biologic clinical-trial and Master Files | Distinct HC document templates per regulatory activity type (e+6 eCTD / f+7 non-eCTD MF) | NO | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/filing-submissions-electronically.html |
| Quality Overall Summary — Chemical Entities (QOS-CE) template (Module 2.3) | HC-provided template (docx/pdf); mandatory Module 2.3 for an ANDS | NO | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/templates.html |
| Comprehensive Summary: Bioequivalence (CS-BE) template — DRAFT (2004-05-18); electronic copy in Module 1.6; supersedes the PCERT BE module | HC-provided template (draft) for ANDS BE data | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/templates/notice-draft-comprehensive-summary-bioequivalence.html |
| eCTD Validation Report (.pdf emailed to sponsor on validation failure) | PDF email attachment listing each error | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/common-electronic-submissions-gateway/frequently-asked-questions.html |
| Acknowledgement messages — MDN, FDA Acknowledgement (Message ID + Core ID), HC Acknowledgement Receipt (Core ID) | Gateway/AS2 messages delivered to WebTrader inbox / AS2 | yes | https://www.hc-sc.gc.ca/dhp-mps/prodpharma/applic-demande/guide-ld/cesg-pcde/faq-longdesc2-eng.php |
| HC-issued lifecycle notices — SDN, SAL, SRL, NOD, NON, NOC, NOD-W, NON-W; Request for Reconsideration | HC-issued letters/notices (received, not authored by portal); sponsor files Q&A response as a new eCTD sequence | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/management-drug-submissions-applications/review.html |
| FDA ESG NextGen WebTrader / AS2 account registration (test then production) | FDA web portal registration + Letter of Non-Repudiation; not an HC form | yes | https://www.fda.gov/industry/create-esg-account/registering-as2-test-account |
| X.509 digital certificate (from a recognized Certificate Authority) | X.509 .cer/.pem public cert uploaded during ESG registration; portal stores/uses it | yes | https://support.globalsign.com/digital-certificates/fda-esg/step-5-set-test-account-fda-esg |
| Fee schedule (SOR/2019-124 Schedule 1) + annual Canada Gazette Notice of Intent | HTML fee table + Canada Gazette Part I/II notice; portal mirrors as versioned, per-grouping CPI-keyed data | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/fees/fees-review-drug-submissions-applications/applicable-fees.html |
| Fees in Respect of Drugs and Medical Devices Order (SOR/2019-124) — Schedules 1, 6, 7 (incl. annual right-to-sell, Oct-1 due) | HTML regulation | yes | https://laws-lois.justice.gc.ca/eng/regulations/SOR-2019-124/FullText.html |
| Small-business status / financial-information attestation (gates 100%/50% remission) | HC attestation form (referenced by REQ-036) | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/fees/fees-review-drug-submissions-applications/invoicing-payment-mitigation.html |
| Fee deferral request (deferral until NOC, s.13) | HC mitigation/invoicing process | yes | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/fees/fees-review-drug-submissions-applications/invoicing-payment-mitigation.html |
| Performance-standard fee-credit (25% credit when HC misses the service standard) | HC guidance / credit process | NO | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/fees/fees-review-drug-submissions-applications/credit-missed-standards.html |
| HPFB Electronic Signatures Policy | Policy document, provided on request (hc.cesg-pcde.sc@canada.ca) | NO | https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/common-electronic-submissions-gateway/frequently-asked-questions.html |
| PIPEDA breach report form (OPC) | Fillable PDF / OPC online breach-reporting form | yes | https://www.priv.gc.ca/media/4844/pipeda_pb_form_e.pdf |
| Cover letter (Module 1, heading 1.0 / m1-0-1-cover-letter leaf) | Sponsor-AUTHORED PDF — HC provides the placement slot only, NOT a fillable template; portal must use its own template auto-populated with the Dossier ID | yes | https://intuitionlabs.ai/articles/health-canada-ectd-submission-guide |