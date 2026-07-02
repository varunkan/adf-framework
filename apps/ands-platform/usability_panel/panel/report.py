"""Aggregation + reporting for the synthetic usability panel."""

from __future__ import annotations

import asyncio
import json

import httpx
import numpy as np

from . import ssr
from .elicit import GROQ_URL, MODEL, load_groq_key
from .personas import PERSONAS, SEGMENTS

CONSTRUCTS = ["ease", "clarity", "trust", "adoption"]


def score_responses(responses: list[dict]) -> list[dict]:
    """SSR-map every construct answer; returns rows with pmf + mean.

    Drops None entries (an elicitation that exhausted its rate-limit retries
    returns None rather than raising) — coverage is asserted by the caller."""
    dropped = sum(1 for r in responses if r is None)
    if dropped:
        print(f"  note: dropping {dropped} failed elicitation(s)")
    responses = [r for r in responses if r]
    rows = []
    for construct in CONSTRUCTS:
        subset = [r for r in responses if construct in r["answers"]]
        if not subset:
            continue
        texts = [r["answers"][construct] for r in subset]
        pmf = ssr.pmf_for_texts(texts, construct)
        means = ssr.mean_rating(pmf)
        for r, p, m in zip(subset, pmf, means):
            rows.append({
                "persona_id": r["persona_id"], "flow_key": r["flow_key"],
                "sample": r["sample"], "construct": construct,
                "text": r["answers"][construct],
                "pmf": p.round(4).tolist(), "mean": round(float(m), 3),
            })
    return rows


def aggregate_cells(rows: list[dict]) -> dict:
    """(flow x construct) survey aggregates + segment means."""
    by_persona = {p["id"]: p for p in PERSONAS}
    cells: dict = {}
    flows = sorted({r["flow_key"] for r in rows})
    for flow in flows:
        cells[flow] = {}
        for construct in CONSTRUCTS:
            sub = [r for r in rows
                   if r["flow_key"] == flow and r["construct"] == construct]
            if not sub:
                continue
            pmf = np.array([r["pmf"] for r in sub])
            agg = ssr.aggregate(pmf)
            segs: dict = {}
            for seg_name, seg_fn in SEGMENTS.items():
                groups: dict[str, list[float]] = {}
                for r in sub:
                    label = seg_fn(by_persona[r["persona_id"]])
                    groups.setdefault(label, []).append(r["mean"])
                segs[seg_name] = {
                    k: round(float(np.mean(v)), 3) for k, v in sorted(groups.items())
                }
            agg["segments"] = segs
            cells[flow][construct] = agg
    return cells


def worst_cells(cells: dict, k: int = 8) -> list[dict]:
    flat = [
        {"flow": f, "construct": c, **{kk: vv for kk, vv in agg.items()
                                       if kk in ("mean", "bottom2", "top2")}}
        for f, cs in cells.items() for c, agg in cs.items()
    ]
    return sorted(flat, key=lambda x: x["mean"])[:k]


async def mine_themes(responses: list[dict]) -> dict[str, str]:
    """Qualitative theme mining per flow (paper App. E) via one LLM pass."""
    responses = [r for r in responses if r]
    key = load_groq_key()
    out: dict[str, str] = {}
    flows = sorted({r["flow_key"] for r in responses})
    async with httpx.AsyncClient() as client:
        for flow in flows:
            fb = [
                f"- [{r['persona_id']}] {r['answers']['feedback']}"
                for r in responses if r["flow_key"] == flow
            ]
            body = {
                "model": MODEL, "temperature": 0.2, "max_tokens": 900,
                "messages": [{
                    "role": "user",
                    "content":
                        "Below is open feedback from a professional usability "
                        "panel about one flow of a Health Canada submission "
                        "tool. Cluster it into the 3-6 dominant themes. For "
                        "each theme give: a short name, how many respondents "
                        "raised it, one representative quote, and ONE concrete "
                        "product change that would address it. Order by "
                        "frequency. Be terse.\n\n" + "\n".join(fb),
                }],
            }
            for attempt in range(4):
                try:
                    r = await client.post(GROQ_URL, json=body, timeout=60,
                                          headers={"Authorization": f"Bearer {key}"})
                    if r.status_code == 429:
                        await asyncio.sleep(4 * (attempt + 1)); continue
                    r.raise_for_status()
                    out[flow] = r.json()["choices"][0]["message"]["content"]
                    break
                except Exception:
                    if attempt == 3:
                        out[flow] = "(theme mining failed)"
                    await asyncio.sleep(2 * (attempt + 1))
    return out


def _bar(dist: list[float], width: int = 24) -> str:
    return " ".join(
        f"{i+1}:{'█' * max(1, round(d * width)) if d > 0.005 else '·'}({d:.0%})"
        for i, d in enumerate(dist)
    )


def render_markdown(cells: dict, themes: dict[str, str],
                    stimuli: list[dict], n_responses: int) -> str:
    titles = {s["flow_key"]: s["title"] for s in stimuli}
    lines = [
        "# ANDS Studio — synthetic usability panel (SSR method)",
        "",
        f"Method: arXiv:2510.08338 adapted to usability testing. "
        f"{len(PERSONAS)} regulatory-professional personas x "
        f"{len(cells)} flows x 2 samples = {n_responses} free-text responses, "
        "mapped to 5-point Likert distributions via semantic-similarity "
        "rating (3 anchor sets per construct, averaged; eps=0.02, T=1).",
        "",
        "## Scores by flow (1=worst, 5=best)",
        "",
        "| Flow | Ease | Clarity | Trust | Adoption |",
        "|---|---|---|---|---|",
    ]
    for flow, cs in cells.items():
        row = [titles.get(flow, flow)]
        for c in CONSTRUCTS:
            row.append(f"**{cs[c]['mean']}**" if c in cs else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## Distributions", ""]
    for flow, cs in cells.items():
        lines.append(f"### {titles.get(flow, flow)}")
        for c in CONSTRUCTS:
            if c in cs:
                a = cs[c]
                lines.append(
                    f"- **{c}** mean {a['mean']} (±{a['std']}) — {_bar(a['distribution'])}")
        lines.append("")
    lines += ["## Weakest cells (fix-first list)", ""]
    for w in worst_cells(cells):
        lines.append(
            f"- {titles.get(w['flow'], w['flow'])} / **{w['construct']}**: "
            f"mean {w['mean']}, bottom-2 share {w['bottom2']:.0%}")
    lines += ["", "## Segment gaps worth noting", ""]
    for flow, cs in cells.items():
        for c, a in cs.items():
            for seg, groups in a["segments"].items():
                vals = list(groups.values())
                if len(vals) == 2 and abs(vals[0] - vals[1]) >= 0.6:
                    g = list(groups.items())
                    lines.append(
                        f"- {titles.get(flow, flow)} / {c}: "
                        f"{g[0][0]} {g[0][1]} vs {g[1][0]} {g[1][1]}")
    lines += ["", "## Qualitative themes per flow", ""]
    for flow, t in themes.items():
        lines += [f"### {titles.get(flow, flow)}", "", t, ""]
    return "\n".join(lines)
