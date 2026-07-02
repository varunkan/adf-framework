"""System-prompt construction for interactive (chat-drafted) eCTD documents.

Pure — no I/O. The deterministic generators in :mod:`generators` fall back to
'—' for anything missing from ``ctx``; this prompt instead tells the model to
*ask* for missing facts and never fabricate regulatory data.
"""

from __future__ import annotations

# Per-document drafting guidance, keyed by generator_key. Keeps the model on
# the structure Health Canada expects for each document type.
_FORM_V_HINT = (
    "Cover the Patented Medicines (Notice of Compliance) Regulations "
    "Form V declaration content: the drug product, the Canadian Reference "
    "Product and its DIN, and — for EACH patent/CSP on the Patent Register "
    "with its expiry — ONE section-5 statement (not addressed / accepts "
    "expiry / alleges invalidity / alleges non-infringement), or an "
    "explicit statement that the Patent Register lists no relevant "
    "patents. Note that where the declaration alleges invalidity or "
    "non-infringement, the sponsor must also serve a Notice of Allegation "
    "(NOA) on the innovator.")
_HINTS = {
    "cover_letter": (
        "Structure: sponsor letterhead block, date, addressee (Health Canada "
        "Therapeutic Products Directorate), Re: line naming the activity type "
        "and product, body identifying the dossier ID / sequence / reference "
        "product, the regulatory contact, and a signature block."),
    "patent_form_v": _FORM_V_HINT,
    "patent_form_iv": _FORM_V_HINT,   # legacy alias (stored section states)
    "ands_attestation": (
        "The attestation must state that the submission is accurate, complete "
        "and not misleading, and confirm: pharmaceutical equivalence to the "
        "Canadian Reference Product (same medicinal ingredients, strength, "
        "dosage form, route), that the bioequivalence evidence supports the "
        "claim, and compliance with the Food and Drugs Act and Regulations. "
        "End with an authorised-signer and date block."),
    "qos_ce_scaffold": (
        "Follow the QOS-CE(BE) structure: 2.3.S drug substance (general "
        "information, manufacture, characterisation, control, reference "
        "standards, container closure, stability) and 2.3.P drug product "
        "(description/composition, pharmaceutical development, manufacture, "
        "excipients, control, reference standards, container closure, "
        "stability), summarising the Module 3 data the user provides."),
    "cs_be": (
        "Summarise the pivotal comparative bioavailability study: test vs "
        "Canadian Reference Product (with DIN), dosage form/strength, study "
        "design (e.g. single-dose fasting crossover), AUC and Cmax 90% "
        "confidence intervals against the 80.00–125.00% limits, the ruleset "
        "applied (ICH M13A or legacy), and a clear bioequivalence "
        "conclusion."),
}


def system_prompt(node: dict, ctx: dict) -> str:
    known = "\n".join(f"- {k}: {v}" for k, v in sorted(ctx.items())
                      if v not in (None, "", "—"))
    hint = _HINTS.get(str(node.get("generator_key") or ""), "")
    return (
        f"You are helping a regulatory-affairs specialist draft the "
        f"\"{node.get('title', '')}\" (eCTD section {node.get('section', '')}) "
        f"for a Health Canada ANDS submission.\n\n"
        f"Purpose of this section: {node.get('purpose', '')}\n"
        f"Health Canada guidance: {node.get('guidance', '')}\n"
        + (f"Document structure: {hint}\n" if hint else "") +
        f"\nKnown facts about this dossier:\n{known or '(none yet — ask for them)'}\n\n"
        "Ask the user, one or two questions at a time, for any missing facts "
        "you need (sponsor/company name, regulatory contact, dates, reference "
        "product, dosage form, etc.) before producing a full draft. Never "
        "invent regulatory facts, dates, patent numbers, DINs, or study "
        "data — if something is still unknown after asking, leave an "
        "explicit [PLACEHOLDER: what's missing] instead of guessing. Keep the "
        "tone formal and precise, matching Health Canada regulatory "
        "correspondence. Once you have enough to draft, write the complete "
        "document text directly in your reply (not a description of it) so "
        "the user can review and save it."
    )
