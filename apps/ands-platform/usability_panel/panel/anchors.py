"""Anchor statement sets for SSR mapping (paper App. C.1).

Design rules from the paper: anchors are short, generic and scale-shaped —
the lowest expresses rejection, the middle indifference/uncertainty, the
highest strong endorsement; intermediates sit semantically between their
neighbours. Multiple sets (m per construct) are averaged because any single
set slightly biases the mapping.

Constructs for usability testing (vs the paper's single purchase-intent):
  ease     — perceived effort to complete the flow (SEQ-style)
  clarity  — did the user understand what to do / what things mean
  trust    — would they rely on it for a real Health Canada submission
  adoption — the purchase-intent analog: would their org adopt/license it
"""

ANCHORS: dict[str, list[list[str]]] = {
    "ease": [
        [
            "This seems very difficult and frustrating to use.",
            "This seems somewhat cumbersome to use.",
            "This seems neither easy nor hard to use.",
            "This seems fairly easy to use.",
            "This seems effortless and very easy to use.",
        ],
        [
            "I would struggle to complete this task.",
            "I would need help to get through parts of this.",
            "I could probably manage this with some effort.",
            "I could do this without much trouble.",
            "I could do this quickly without any help.",
        ],
        [
            "The workflow feels confusing and overwhelming.",
            "The workflow feels awkward in places.",
            "The workflow feels acceptable.",
            "The workflow feels smooth.",
            "The workflow feels completely intuitive.",
        ],
    ],
    "clarity": [
        [
            "I have no idea what I am supposed to do here.",
            "Several parts left me unsure what to do.",
            "I mostly understood what to do.",
            "It was clear what to do at each step.",
            "Everything was immediately obvious and self-explanatory.",
        ],
        [
            "The terms and labels make no sense to me.",
            "Some terms and labels are confusing.",
            "The terminology is understandable overall.",
            "The terms and guidance are clear.",
            "The terminology and guidance are perfectly clear and helpful.",
        ],
        [
            "I would get lost navigating this.",
            "I am not always sure where to go next.",
            "I can generally find my way around.",
            "Navigation and next steps are clear.",
            "I always know exactly where I am and what comes next.",
        ],
    ],
    "trust": [
        [
            "I would never trust this for a real submission.",
            "I doubt this would hold up in a real submission.",
            "I am unsure whether I could rely on this.",
            "I would mostly trust this, with some double-checking.",
            "I would fully trust this for a real submission.",
        ],
        [
            "This would create compliance risk for my company.",
            "I would worry about errors slipping through.",
            "It seems about as reliable as my current process.",
            "It seems to reduce the risk of mistakes.",
            "It clearly strengthens compliance and catches mistakes.",
        ],
        [
            "The regulatory content seems wrong or made up.",
            "The regulatory content seems superficial.",
            "The regulatory content seems plausible.",
            "The regulatory content seems accurate.",
            "The regulatory content seems rigorous and authoritative.",
        ],
    ],
    "adoption": [
        [
            "It's very unlikely we would adopt this tool.",
            "It's rather unlikely we would adopt this tool.",
            "We might or might not adopt this tool.",
            "It's likely we would adopt this tool.",
            "It's very likely we would adopt this tool.",
        ],
        [
            "I would not recommend buying this.",
            "I probably wouldn't push for this.",
            "I am on the fence about recommending this.",
            "I would probably recommend we get this.",
            "I would strongly push my organization to get this.",
        ],
        [
            "Switching to this is out of the question.",
            "I see little reason to switch to this.",
            "I might pilot this alongside what we have today.",
            "I would move part of our work into this.",
            "I would make this our main tool.",
        ],
    ],
}
