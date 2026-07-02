"""Semantic Similarity Rating — the core mapping from free text to a
5-point Likert probability mass function (paper App. A.4.3, eqs. 7-9).

For a response text t and one anchor set {sigma_1..sigma_5}:

    gamma_r      = cos(v_{sigma_r}, v_t)                        (eq. 7)
    p(r)  propto  gamma_r - gamma_min + eps * delta(r, argmin)  (eq. 8)
    p_T(r) propto p(r)^(1/T)                                    (eq. 9)

Subtracting the per-set minimum restores dynamic range (raw cosine
similarities between any two English statements are all "close"); eps keeps
the weakest anchor at a small nonzero likelihood; T controls smearing.
pmfs are computed per anchor set, then averaged over the m sets.

Embeddings: sentence-transformers all-MiniLM-L6-v2 (contextual, local). The
paper used OpenAI text-embedding-3-small and notes the embedding model is a
swappable detail — but it must be CONTEXTUAL: static token embeddings
(model2vec) fail ordinality on negation-heavy statements ("I would never pay
for this" vs "I would replace my current tools with this" share too much
surface vocabulary), which we caught in test_positive_beats_negative.
"""

from __future__ import annotations

import numpy as np

from .anchors import ANCHORS

EPS = 0.02
# T=0.5 sharpens the similarity->pmf mapping. Calibration (see CALIBRATION)
# showed T=1.0 compresses the scale so hard that the trust ceiling is 3.55 —
# no product could ever score 4. At 0.5 ordinality still holds (bake-off) and
# the floor->ceiling range roughly doubles.
TEMP = 0.5

# Anchor-free absolute thresholds are meaningless in SSR space — the mapping
# has a construct-specific floor and ceiling. These batteries define them:
# maximally satisfied / dissatisfied professional statements. Scores are
# interpreted as position between the two (see normalize()).
CALIBRATION = {
    "ceiling": {
        "ease": ["This is genuinely effortless — the smoothest regulatory tool I've used.",
                 "Anyone on my team could do this without training; it's that easy.",
                 "Completely intuitive; I flew through the whole flow on the first try."],
        "clarity": ["Every label, step and term was immediately clear — nothing confused me.",
                    "The guidance explains everything; I always knew exactly what to do next.",
                    "Crystal clear from start to finish, even the regulatory jargon."],
        "trust": ["I would file a real submission through this tomorrow without hesitation.",
                  "This is more rigorous than my current validated process; I trust it fully.",
                  "The compliance checks are airtight — I'd stake my license on it."],
        "adoption": ["We are buying this — I'll push procurement to sign this week.",
                     "I'd replace our current tools with this immediately.",
                     "Absolutely adopting it; this is exactly what our team needs."],
    },
    "floor": {
        "ease": ["Painful and clumsy; every step fought me.",
                 "Unusable — I gave up halfway.",
                 "So awkward I'd need days of training."],
        "clarity": ["I never understood what it wanted from me.",
                    "The labels are gibberish to me.",
                    "Totally lost from the first screen."],
        "trust": ["I would never risk a real filing on this.",
                  "This would get my client a refusal letter.",
                  "The regulatory content is not credible at all."],
        "adoption": ["We will never buy this.",
                     "I'd advise everyone against adopting it.",
                     "Not a chance — we keep our current process."],
    },
}

_bounds_cache: dict[str, tuple[float, float]] = {}


def bounds(construct: str, temp: float = TEMP) -> tuple[float, float]:
    """(floor, ceiling) mean-rating for a construct at this temperature."""
    key = f"{construct}@{temp}"
    if key not in _bounds_cache:
        lo = mean_rating(pmf_for_texts(
            CALIBRATION["floor"][construct], construct, temp=temp)).mean()
        hi = mean_rating(pmf_for_texts(
            CALIBRATION["ceiling"][construct], construct, temp=temp)).mean()
        _bounds_cache[key] = (float(lo), float(hi))
    return _bounds_cache[key]


def normalize(mean: float, construct: str, temp: float = TEMP) -> float:
    """Position of a mean rating between the calibrated floor (0) and
    ceiling (1) for its construct — the scale satisfaction is judged on."""
    lo, hi = bounds(construct, temp)
    return (mean - lo) / (hi - lo) if hi > lo else 0.0

_model = None
_anchor_vecs: dict[str, list[np.ndarray]] = {}


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        # bake-off vs MiniLM-L6 and mpnet-base: bge-small gives the largest
        # worst-case pos/neg gap (+1.04) with non-degenerate pmfs (peak <= .38)
        _model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _model


def _unit(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float64)
    return m / np.clip(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12, None)


def _anchor_matrix(construct: str) -> list[np.ndarray]:
    """One (5, dim) unit matrix per anchor set, cached."""
    if construct not in _anchor_vecs:
        sets = ANCHORS[construct]
        model = _get_model()
        _anchor_vecs[construct] = [_unit(np.asarray(model.encode(s))) for s in sets]
    return _anchor_vecs[construct]


def pmf_for_texts(
    texts: list[str], construct: str, eps: float = EPS, temp: float = TEMP
) -> np.ndarray:
    """Map N free-text responses to (N, 5) Likert pmfs for one construct."""
    if construct not in ANCHORS:
        raise KeyError(f"unknown construct {construct!r}")
    model = _get_model()
    tv = _unit(np.asarray(model.encode(list(texts))))          # (N, dim)
    per_set = []
    for anchors in _anchor_matrix(construct):                   # each (5, dim)
        gamma = tv @ anchors.T                                  # (N, 5)  eq. 7
        gmin = gamma.min(axis=1, keepdims=True)
        p = gamma - gmin                                        # eq. 8
        # the argmin anchor got exactly 0 — give it the eps floor
        p[np.arange(len(p)), gamma.argmin(axis=1)] = eps
        p = p / p.sum(axis=1, keepdims=True)
        per_set.append(p)
    pmf = np.mean(per_set, axis=0)                              # average m sets
    if temp != 1.0:
        pmf = pmf ** (1.0 / temp)                               # eq. 9
    return pmf / pmf.sum(axis=1, keepdims=True)


def mean_rating(pmf: np.ndarray) -> np.ndarray:
    """Expected Likert value per row: sum_i i * p(i)  (paper eq. 2)."""
    return pmf @ np.arange(1, 6)


def aggregate(pmf: np.ndarray) -> dict:
    """Survey-level summary of a stack of respondent pmfs (paper eq. 1)."""
    dist = pmf.mean(axis=0)
    means = mean_rating(pmf)
    return {
        "distribution": dist.round(4).tolist(),
        "mean": round(float(means.mean()), 3),
        "std": round(float(means.std()), 3),
        "top2": round(float(dist[3] + dist[4]), 4),
        "bottom2": round(float(dist[0] + dist[1]), 4),
        "n": int(pmf.shape[0]),
    }
