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
