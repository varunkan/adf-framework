# Campaign log — Regulatory persona + dosage-form swarm (every drug sold in Canada)

Goal (user, 2026-07-10): run the next round of regulatory **persona-based** testing
AND **every dosage form / drug type sold in Canada** through the ANDS portal's
regulatory engine — leave no drug category out. Find genuine gaps (not re-report
already-covered rules), verify them, fix TDD-first, commit + log each.

## Coverage baseline (as of HEAD `c8e442d`)
- Submission types (`content_model.SUBMISSION_TYPES`): NDS, ANDS, SNDS, SANDS, DIN.
- Fee drug-types (`fees.DRUG_TYPES` / `RIGHT_TO_SELL_FEES`): prescription,
  non-prescription, disinfectant, biocide (+ small-business remission,
  comparative-studies ANDS fee, right-to-sell annual).
- BE dosage-form classes (`bioequivalence.DOSAGE_FORM_CLASSES`): IR-solid-oral,
  MR, complex-parenteral, inhalation, topical, other.
- Validation (`validation.py`): eCTD backbone — General/PDF/XML/Referenced/
  ICH-Backbone/Regional/STF/REP + REP DIN↔Dossier↔Company agreement.
- Prior swarm rounds (r1–r11) already added: radiopharm-DIN, biosimilar Form V,
  controlled-substance gating, complex-parenteral/microsphere, RTS fee tiering,
  second-entry SABA MDI PD, small-business, topical.

## Drug-archetype taxonomy under test (comprehensive, all Canadian categories)
Small-molecule Rx by dosage form × pathway (IR/MR solid-oral, oral liquid,
simple + complex parenteral, MDI/DPI inhalation, nasal, topical, transdermal,
ophthalmic, otic, rectal/vaginal, ODT/SL/buccal); innovator NDS + SNDS;
biologics (mAb, biosimilar, vaccine, blood/plasma product, insulin, gene/cell
therapy); radiopharmaceutical (Sched C); controlled substances (narcotic,
targeted/benzo, incl. fentanyl transdermal); OTC/self-care monograph;
disinfectant + biocide; veterinary; large-volume parenteral / medical gas;
cross-cutting fee contexts (small-business, right-to-sell).

## Personas (regulatory lenses)
Generic RA (ANDS/BE), Innovator RA (NDS), Biologics/Biosimilar RA, Radiopharm RA,
Controlled-Substances compliance, OTC/Self-Care RA, Disinfectant/Biocide RA,
CMC/Quality reviewer, Bioequivalence scientist, Fees/Business officer, eCTD
Publisher/RegOps, Veterinary RA, HC Submission Reviewer (adversarial).

## Method
Workflow `persona-dosage-swarm`: pipeline over archetypes —
1. **Probe** — one agent per archetype (as the mapped persona) reads the CURRENT
   modules and reports concrete gaps vs. real Health Canada rules (severity +
   HC source + proposed test).
2. **Verify** — adversarial verifier re-reads the current code to confirm each
   gap is genuine (not already covered) and web/knowledge-checks the factual
   claim; marks CONFIRMED/REJECTED + material?.
3. **Synthesize** — dedup + rank CONFIRMED gaps → backlog.
Then: fix each CONFIRMED material gap TDD-first (RED→GREEN), commit per unit,
append an entry here + in ACTIVITY_LOG.md, re-run the suite.

---

## Rounds

### Round 12 — kickoff, then RE-TARGET
- **VOIDED against the monolith.** The first probe was pointed at the now-deleted
  monolith `apps/ands-submission-portal` — wrong app. Discarded.
- **The real target is the mesh** `apps/ands-platform/services/*`. The regulatory
  logic lives in the **dossier** service (`be_ruleset.py`, `fees.py`,
  `content_model.py`, `ectd_validation.py`, `comparative_evidence.py`,
  `controlled_substances.py`, `special_pathways.py`, `monograph.py`,
  `product_scope.py`, `form_schemas.py`, `section_tree.py`), plus the **journey**,
  **validation**, **fees**, and **readiness** services. Mesh dossier baseline:
  **719 tests green** (`apps/ands-platform/.venv`).
- Re-running the same persona × Canadian-dosage-form/drug-type taxonomy against
  the mesh modules. Results below.
