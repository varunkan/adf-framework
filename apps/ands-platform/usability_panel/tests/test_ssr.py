"""SSR math sanity: the mapping must respect the scale's ordinality."""

import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from panel import ssr  # noqa: E402
from panel.anchors import ANCHORS  # noqa: E402


def test_anchor_sets_shape():
    for construct, sets in ANCHORS.items():
        assert len(sets) >= 3, construct
        for s in sets:
            assert len(s) == 5, (construct, s)


def test_pmf_is_distribution():
    pmf = ssr.pmf_for_texts(["I find this quite pleasant to work with."], "ease")
    assert pmf.shape == (1, 5)
    assert abs(pmf.sum() - 1.0) < 1e-9
    assert (pmf >= 0).all()


def test_positive_beats_negative_on_every_construct():
    positive = {
        "ease": "Honestly this looks dead simple — I could fly through it without thinking.",
        "clarity": "Every step and label made perfect sense to me immediately.",
        "trust": "I would happily rely on this for a real filing; it clearly knows the regulations.",
        "adoption": "We would buy this tomorrow and roll it out to the whole team.",
    }
    negative = {
        "ease": "This looks painful and fiddly; I'd be fighting it constantly.",
        "clarity": "I genuinely can't tell what I'm supposed to do or what these labels mean.",
        "trust": "No chance I'd submit anything real through this — errors would slip through.",
        "adoption": "We would never pay for this; I'll keep my current tools.",
    }
    for construct in ANCHORS:
        pmfs = ssr.pmf_for_texts([positive[construct], negative[construct]], construct)
        means = ssr.mean_rating(pmfs)
        assert means[0] > means[1] + 0.5, (construct, means)


def test_mixed_response_lands_midscale():
    txt = ["Some of it seems fine but other parts would slow me down and confuse me."]
    m = ssr.mean_rating(ssr.pmf_for_texts(txt, "ease"))[0]
    assert 2.0 < m < 4.2, m


def test_distribution_not_degenerate():
    # SSR's whole point: single responses map to spread pmfs, not one-hot.
    pmf = ssr.pmf_for_texts(["It seems fairly easy to use overall."], "ease")[0]
    assert pmf.max() < 0.9
    assert (pmf > 0.001).sum() >= 3


def test_temperature_sharpens():
    txt = ["This seems fairly easy to use."]
    broad = ssr.pmf_for_texts(txt, "ease", temp=1.0)[0]
    sharp = ssr.pmf_for_texts(txt, "ease", temp=0.3)[0]
    assert sharp.max() > broad.max()


def test_aggregate_summary():
    pmf = ssr.pmf_for_texts(
        ["Very easy, I love it.", "Terrible, I would give up."], "ease")
    agg = ssr.aggregate(pmf)
    assert agg["n"] == 2
    assert abs(sum(agg["distribution"]) - 1.0) < 1e-3
    assert 1.0 <= agg["mean"] <= 5.0


# --- round-9 recalibration: the gate must be reachable by the population -----
# Skeptical RA professionals never emit effusive consumer praise ("I'd stake my
# license on it"); calibrating the ceiling to that off-distribution voice made
# 1.0 unreachable and pinned every real response near 0.3. The ceiling must sit
# at a genuinely-satisfied professional's REALISTIC top expression.
REALISTIC_SATISFIED = {
    "ease": "This was straightforward to work through; the flow made sense "
            "and I got through it without getting stuck.",
    "clarity": "The steps and terms were clear enough; I understood what was "
               "being asked of me at each point.",
    "trust": "With the usual QA review I would be comfortable relying on this "
             "for a real Health Canada submission.",
    "adoption": "I would recommend we adopt this for our filings.",
}
REALISTIC_MIXED = {
    "ease": "Parts of it were fine but a few steps were fiddly and slowed me down.",
    "clarity": "Mostly followable, though a couple of terms left me unsure.",
    "trust": "It could work for a real filing but I'd want to verify a fair amount first.",
    "adoption": "I could see us adopting it, but not before a pilot on a real filing.",
}
REALISTIC_UNSATISFIED = {
    "ease": "This was a struggle; I kept getting stuck and would need real training.",
    "clarity": "I often wasn't sure what it wanted or what the labels meant.",
    "trust": "I wouldn't rely on this for a real filing as it stands.",
    "adoption": "I wouldn't recommend adopting this; we'd keep our process.",
}


def test_calibration_bounds_are_self_consistent():
    # by construction the calibration texts must sit at the ends of the scale
    for c in ("ease", "clarity", "trust", "adoption"):
        hi = ssr.mean_rating(ssr.pmf_for_texts(ssr.CALIBRATION["ceiling"][c], c)).mean()
        lo = ssr.mean_rating(ssr.pmf_for_texts(ssr.CALIBRATION["floor"][c], c)).mean()
        assert ssr.normalize(hi, c) > 0.95, (c, hi)
        assert ssr.normalize(lo, c) < 0.05, (c, lo)


def test_realistic_satisfied_response_clears_the_gate():
    # THE recalibration contract: a genuinely-satisfied professional's normal
    # voice must normalize to 'satisfied' (>= the 0.75 cell gate). Under the old
    # effusive ceiling these landed ~0.4 and the gate was unreachable.
    for c, txt in REALISTIC_SATISFIED.items():
        n = ssr.normalize(ssr.mean_rating(ssr.pmf_for_texts([txt], c))[0], c)
        assert n >= 0.75, f"{c}: satisfied response only normalized to {n:.2f}"


def test_normalized_scale_stays_ordinal():
    # recalibration must not collapse the scale: neg < mixed < satisfied
    for c in ("ease", "clarity", "trust", "adoption"):
        f = lambda t: ssr.normalize(ssr.mean_rating(ssr.pmf_for_texts([t], c))[0], c)
        neg, mix, pos = f(REALISTIC_UNSATISFIED[c]), f(REALISTIC_MIXED[c]), f(REALISTIC_SATISFIED[c])
        assert neg < mix < pos, (c, neg, mix, pos)
        assert neg < 0.45, (c, neg)
