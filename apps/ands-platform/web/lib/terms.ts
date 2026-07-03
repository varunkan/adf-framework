// Plain-language translation of HC jargon — mirrors the monolith's strings.
// Used by <Term> to explain a term inline on first use (JRNY-REQ / UI-REQ-012).
export const TERMS: Record<string, string> = {
  ANDS:
    "Abbreviated New Drug Submission — the shortcut pathway for a generic copy " +
    "of an already-approved brand drug. You prove your version is the 'same' " +
    "(equivalent + bioequivalent) instead of repeating the original trials.",
  NDS:
    "New Drug Submission — the full innovator pathway, with complete safety and " +
    "efficacy evidence (Modules 2–5).",
  CRP:
    "Canadian Reference Product — the already-approved Canadian brand drug your " +
    "generic is compared against.",
  bioequivalence:
    "Proof your generic behaves the same in the body as the reference product " +
    "(AUC and Cmax within 80–125%). For immediate-release solid orals filed " +
    "from 2025-12-27, ICH M13A requires the full Cmax 90% confidence interval.",
  "Dossier ID":
    "The permanent file number for one product at Health Canada (one letter + " +
    "6–7 digits, e.g. e123456). You reuse it forever. Request it at most 8 " +
    "weeks before filing.",
  "Company ID":
    "A 5-digit number Health Canada assigns to your company. You need it before " +
    "you can transmit.",
  eCTD:
    "electronic Common Technical Document — the strict folder + XML structure " +
    "Health Canada's systems read. Modern software writes the XML for you; your " +
    "job is to put the right document in the right module.",
  "Module 1":
    "The Canada-specific administrative part of the submission (cover letter, " +
    "forms, the bilingual Product Monograph). Modules 2–5 are the same worldwide.",
  QOS: "Quality Overall Summary — the Module 2.3 summary of your CMC/quality data.",
  CMC: "Chemistry, Manufacturing and Controls — Module 3, how the drug is made and tested.",
  CESG:
    "Common Electronic Submissions Gateway — Health Canada's official channel " +
    "for transmitting an eCTD. It runs on the US FDA's shared ESG " +
    "infrastructure, so you register once as an FDA ESG Trading Partner and tag " +
    "the package 'HC' to route it to Health Canada. Applies whenever you " +
    "transmit a sequence. (Health Canada CESG guidance, canada.ca.)",
  "FDA-ESG":
    "US FDA Electronic Submissions Gateway — the shared transmission " +
    "infrastructure Canada's CESG uses. Because it's shared, a Canadian ANDS " +
    "legitimately produces FDA-side receipts (an FDA MDN, then an FDA ACK) " +
    "before the Health Canada acknowledgement routes back. Applies at the " +
    "transmit step.",
  MDN:
    "Message Delivery Notification — the first receipt from the FDA ESG " +
    "confirming your transmission physically arrived at the shared gateway. It " +
    "proves delivery, not acceptance. Applies at the transmit step; a Canadian " +
    "ANDS gets an FDA-side MDN because CESG rides the shared FDA ESG.",
  ACK:
    "Acknowledgement Receipt — routes back through the gateway after the MDN. " +
    "The FDA ACK confirms the ESG accepted the package; the Health Canada ACK " +
    "(Core ID) is the proof Health Canada itself has your submission. Applies " +
    "at the transmit step.",
  "Core ID":
    "The identifier on the Health Canada acknowledgement — the final of the " +
    "three transmit receipts and the real proof Health Canada has your " +
    "submission. Don't stop at the FDA ACK. Applies at the transmit step.",
  MFA:
    "Multi-factor authentication — a second code from your phone (an " +
    "authenticator app) on top of your password. Applies at sign-in once you " +
    "turn it on, or when your workspace requires it.",
  TOTP:
    "Time-based One-Time Password — the rotating 6-digit code from an " +
    "authenticator app (a second sign-in factor beyond your password). Applies " +
    "when MFA is turned on for your account.",
  "s.5":
    "Section 5 of the PM(NOC) Regulations — the rule that makes a generic " +
    "address every patent on the reference product's register (via Form V). " +
    "Applies when the reference product has listed patents.",
  "s.6":
    "Section 6 of the PM(NOC) Regulations — the innovator's right to start a " +
    "court action within 45 days of an NOA to block your approval. Applies once " +
    "you serve a Notice of Allegation.",
  "AUC 90% CI":
    "The 90% confidence interval on AUC (total drug exposure over time) — it " +
    "must sit inside the 80.00–125.00% window to prove bioequivalence. Applies " +
    "to your comparative bioequivalence (CS-BE) study data.",
  SAL:
    "Screening Acceptance Letter — Health Canada confirms your submission " +
    "passed the completeness check and enters review. Applies during screening " +
    "(~45 days after transmit).",
  SRL:
    "Screening Rejection Letter — the submission failed the completeness check " +
    "and is not accepted into review. Applies during screening.",
  "24-month stay":
    "The pause on your approval that starts when the innovator commences an " +
    "s.6 court action after your NOA — up to 24 months, or until the court " +
    "decides. Applies once an s.6 action is filed.",
  NOC:
    "Notice of Compliance — approval. You also get a DIN (Drug Identification " +
    "Number) and may sell the drug.",
  NOD:
    "Notice of Deficiency — serious gaps; the review is stopped and you respond " +
    "in 90 days.",
  NON:
    "Notice of Non-compliance — the review finished and fell short; you get a " +
    "second cycle (respond in 45/90 days).",
  clarifax:
    "A clarification request during the science review — clarify or re-analyse " +
    "data you already filed (not new data). Tight window (15 days for a 180-day ANDS).",
  SDN:
    "Screening Deficiency Notice — 'something's missing, send it in 45 days'. " +
    "This is the completeness check, not the science review.",
  "Right to Sell":
    "An annual obligation (with fee) to keep your DIN active, due each " +
    "October 1. Applies to every marketed DIN after NOC.",
  "Right-to-Sell":
    "An annual obligation (with fee) to keep your DIN active, due each " +
    "October 1. Applies to every marketed DIN after NOC.",
  "small business":
    "A status (granted BEFORE you file) that gives a 50% fee reduction — and a " +
    "full waiver on your first-ever submission. Filing first forfeits it.",
  clock:
    "Health Canada's target review days count only THEIR time and pause while " +
    "they wait on you, so real elapsed time is longer.",
  REP:
    "Regulatory Enrolment Process — the mandatory web templates (since Oct 2020) " +
    "that generate the application XML. Replaces the old HC/SC 3011 form.",
  PMI:
    "Patient Medication Information — plain-language medication info written at a " +
    "Grade 6–8 reading level, bilingual.",
  "Form IV":
    "The innovator's Patent List under the PM(NOC) Regulations — the patents " +
    "the brand registered against its product. Generics don't file Form IV; " +
    "they answer it with Form V.",
  "Form V":
    "The generic's declaration under s.5 of the PM(NOC) Regulations: for every " +
    "patent/CSP on the reference product's register you either accept waiting " +
    "for expiry or allege invalidity/non-infringement (which triggers a Notice " +
    "of Allegation).",
  NOA:
    "Notice of Allegation — your Form V challenge served on the brand. They " +
    "have 45 days to sue; doing so triggers a stay of your approval of up to " +
    "24 months.",
  DIN:
    "Drug Identification Number — the 8-digit number on every marketed drug in " +
    "Canada, assigned at NOC. It identifies the product (dose form, strength, " +
    "route), not the submission.",
  sequence:
    "One numbered eCTD package in the dossier's lifetime (0000 = the original " +
    "filing; 0001+ = responses and post-approval changes). Each sequence " +
    "amends the one before it — the 'current view' is the merged result.",
  SANDS:
    "Supplemental ANDS — the pathway for changing an already-approved generic " +
    "(new strength, new indication text, manufacturing change requiring " +
    "review).",
  OSIP:
    "Health Canada's Office of Submission and Intellectual Property — the " +
    "office that issues Company IDs and Dossier IDs and runs intake for " +
    "submissions.",
  "Product Monograph":
    "The authoritative bilingual label: Part I for practitioners, Part II " +
    "science, Part III patient information. Generics align theirs to the " +
    "reference product's monograph. Filed as structured XML (XML PM) on " +
    "Health Canada's mandated stylesheet.",
  "CS-BE":
    "Comparative Studies–Bioequivalence: the study package (design, AUC and " +
    "Cmax 90% confidence intervals vs the 80.00–125.00% window) that proves " +
    "your generic performs the same in the body.",
};

export const TERM_KEYS = Object.keys(TERMS).sort((a, b) => b.length - a.length);
