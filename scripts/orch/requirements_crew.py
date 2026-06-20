#!/usr/bin/env python3
"""ADF requirements crew — the multi-agent system that RESEARCHES, DRAFTS, and PO-
VALIDATES a detailed requirements document before any code is written. Each subagent is
a SMALL, precise task routed (via model_router) to the model best suited to it; the
parallel waves reuse build_crew's Kahn-DAG + run_crew. Waves:

  0 plan       — Nemotron Ultra decomposes the request → {queries, categories, seed_urls}
  1 research   — web_scraper gathers a cited corpus (+ pre-ingested user sources)
  2 draft      — per category, EARS items grounded in the corpus (Nemotron Super) [parallel]
  3 po         — DeepSeek R1 verifies (measurability/traceability/completeness) ∥ Nemotron
                 Ultra judges (domain/holistic) + reconciles sources; clarifying-questions [parallel]
  4 head       — Opus synthesizes ONE coherent PRD; DeepSeek R1 cross-checks

Writes specs/<id>/{spec.md, problem-statement.md, requirements-draft.json (with
sources[] traceability), po-validation.md} + judge-verdicts/phase-2.md. The crew never
writes code — it produces requirements the human confirms.

  run(feature_id, requirement, sources, specs_dir, verdict_dir,
      complete=None, gather=None) -> result dict

`complete(prompt, role, system=None)` and `gather(queries, urls)` are injectable for
tests; default to model_router.complete + web_scraper.gather.
"""
import json
import os
import re

import build_crew


def _complete(prompt, role, system=None):
    import model_router
    res = model_router.complete(prompt, role, system=system)
    return (res[0] if res else "") or ""


def _gather(queries, urls):
    import web_scraper
    return web_scraper.gather(queries=queries, urls=urls,
                              complete=lambda p, r: _model_tuple(p, r))


def _model_tuple(prompt, role):
    import model_router
    return model_router.complete(prompt, role)


def _json(text, default):
    """Tolerant JSON parse of a model reply: strip code fences, grab the outermost
    object/array. Returns `default` on failure (a model that rambles never crashes)."""
    if not text:
        return default
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    for pat in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pat, t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    try:
        return json.loads(t)
    except ValueError:
        return default


_PLAN_SYS = ("You are a senior requirements analyst (BMAD Analyst). Decompose the "
             "request into a research plan. Reply ONLY JSON: "
             '{"queries":[..3-6 web search queries..],"categories":[..requirement '
             'categories e.g. functional,non_functional,data,roles,acceptance..],'
             '"seed_urls":[..authoritative URLs to read..]}')

_DRAFT_SYS = ("You are a product manager (BMAD PM) writing PRECISE, TESTABLE EARS "
              "requirements GROUNDED in the research corpus + user sources. Reply ONLY "
              'JSON: {"requirements":[{"id","shall","acceptance","rationale","source"}]}'
              ". Every requirement must cite a source. Do NOT invent domain facts.")

_PO_SYS = ("You are the BMAD Product Owner / Validation Architect. Rigorously check the "
           "draft for the given lens. Reply ONLY JSON: "
           '{"pass":bool,"gaps":[..specific issues..]}')

_Q_SYS = ("You are the BMAD PO facilitating requirements confirmation. From the draft + "
          "gaps, list what is genuinely AMBIGUOUS and needs the user's decision, plus "
          'improvement suggestions. Reply ONLY JSON: {"questions":[..],"improvements":[..]}')

_HEAD_SYS = ("You are a principal engineer synthesizing ONE coherent PRD from many "
             "fragments (BMAD create-prd discipline): consolidate, DEDUPE, resolve "
             "conflicts, ensure every requirement is measurable + testable + traceable + "
             "cited, integrate the PO gaps, and rank source authority (user docs/mockups "
             "> web). Reply ONLY JSON: "
             '{"problem_statement","requirements":[{"id","shall","acceptance","source"}],'
             '"assumptions":[],"out_of_scope":[],"open_questions":[]}')

_XCHECK_SYS = ("You are an adversarial reviewer (different model than the author). Try to "
               "REFUTE the PRD: missing requirements, untestable claims, unsourced domain "
               'facts, source conflicts. Reply ONLY JSON: {"issues":[..]}')


def _corpus_text(corpus, limit=9000):
    out = []
    for n in corpus:
        out.append(f"### {n.get('title','')} ({n.get('url','')})\n{n.get('facts','')}")
    return "\n\n".join(out)[:limit]


def run(feature_id, requirement, sources=None, specs_dir=None, verdict_dir=None,
        complete=None, gather=None, parallelism=4):
    """Run the crew. `sources` is a list of pre-ingested {source, requirements} dicts
    (docs/data/repo) + optional {url} entries. Returns the result dict and writes the
    spec artifacts. complete/gather injectable for tests."""
    complete = complete or _complete
    gather = gather or _gather
    sources = sources or []
    user_urls = [s["url"] for s in sources if s.get("url")]
    user_reqs = "\n".join(
        f"[{s.get('source','source')}] {s.get('requirements','')}"
        for s in sources if s.get("requirements"))

    # Wave 0 — plan (Nemotron Ultra)
    plan = _json(complete(
        f"REQUEST:\n{requirement}\n\nUSER-PROVIDED REQUIREMENTS (authoritative):\n"
        f"{user_reqs or '(none)'}", "plan", _PLAN_SYS),
        {"queries": [requirement[:120]], "categories": ["functional"], "seed_urls": []})
    categories = plan.get("categories") or ["functional"]

    # Wave 1 — research (web_scraper corpus + user URLs/seed URLs)
    corpus = gather(plan.get("queries") or [], user_urls + (plan.get("seed_urls") or []))
    corpus_text = _corpus_text(corpus)
    sources_list = sorted({n.get("url") for n in corpus if n.get("url")} |
                          {s.get("source") for s in sources if s.get("source")})

    # Wave 2 — draft per category (parallel via build_crew.run_crew)
    def run_draft(agent, prior):
        cat = agent.name
        out = complete(
            f"CATEGORY: {cat}\nREQUEST: {requirement}\n\nRESEARCH CORPUS:\n{corpus_text}"
            f"\n\nUSER REQUIREMENTS:\n{user_reqs or '(none)'}", "draft", _DRAFT_SYS)
        return True, [(cat, out)], cat
    draft_agents = [build_crew.BuildAgent(c, c) for c in categories]
    draft_res = build_crew.run_crew(draft_agents, run_draft, parallelism=parallelism)
    drafts = {k: _json(v, {"requirements": []}) for k, v in draft_res["files"].items()}
    all_reqs = [r for d in drafts.values() for r in (d.get("requirements") or [])]
    draft_text = json.dumps(all_reqs)[:9000]

    # Wave 3 — PO validation (parallel: R1 verify ∥ Ultra judge + questions)
    def run_po(agent, prior):
        if agent.name == "questions":
            out = complete(f"DRAFT:\n{draft_text}", "questions", _Q_SYS)
        else:
            role = "verify" if agent.name == "rigor" else "judge"
            lens = ("measurability, testability, traceability, completeness"
                    if agent.name == "rigor"
                    else "domain-compliance, holistic coherence, source reconciliation")
            out = complete(f"LENS: {lens}\nDRAFT:\n{draft_text}\n\nSOURCES: {sources_list}",
                           role, _PO_SYS)
        return True, [(agent.name, out)], agent.name
    po_agents = [build_crew.BuildAgent(n, n) for n in ("rigor", "judge", "questions")]
    po_res = build_crew.run_crew(po_agents, run_po, parallelism=parallelism)
    rigor = _json(po_res["files"].get("rigor", ""), {"pass": True, "gaps": []})
    judge = _json(po_res["files"].get("judge", ""), {"pass": True, "gaps": []})
    qs = _json(po_res["files"].get("questions", ""), {"questions": [], "improvements": []})
    # perspective-diverse: a gap counts if EITHER reasoner flags it
    po_gaps = list(rigor.get("gaps") or []) + list(judge.get("gaps") or [])
    po_pass = bool(rigor.get("pass")) and bool(judge.get("pass")) and not po_gaps

    # Wave 4 — synthesis head (Opus) + adversarial cross-check (R1)
    head = _json(complete(
        f"REQUEST: {requirement}\nCATEGORIES: {categories}\nDRAFTS:\n{draft_text}\n\n"
        f"PO GAPS:\n{po_gaps}\n\nCORPUS:\n{corpus_text}\n\nSOURCES: {sources_list}",
        "synthesis", _HEAD_SYS),
        {"problem_statement": requirement, "requirements": all_reqs,
         "assumptions": [], "out_of_scope": [], "open_questions": []})
    xcheck = _json(complete(f"PRD:\n{json.dumps(head)[:9000]}", "cross_check", _XCHECK_SYS),
                   {"issues": []})

    open_questions = list(qs.get("questions") or []) + list(head.get("open_questions") or [])
    result = {
        "feature_id": feature_id,
        "problem_statement": head.get("problem_statement") or requirement,
        "requirements": head.get("requirements") or all_reqs,
        "assumptions": head.get("assumptions") or [],
        "out_of_scope": head.get("out_of_scope") or [],
        "sources": sources_list,
        "open_questions": open_questions,
        "improvements": qs.get("improvements") or [],
        "po": {"pass": po_pass, "gaps": po_gaps},
        "cross_check": xcheck.get("issues") or [],
        "models": "free NVIDIA bulk + Opus head",
    }
    if specs_dir:
        _write_artifacts(specs_dir, verdict_dir, feature_id, result)
    return result


def _write_artifacts(specs_dir, verdict_dir, feature_id, r):
    os.makedirs(specs_dir, exist_ok=True)
    with open(os.path.join(specs_dir, "requirements-draft.json"), "w",
              encoding="utf-8") as f:
        json.dump(r, f, indent=2, sort_keys=True)
    with open(os.path.join(specs_dir, "problem-statement.md"), "w",
              encoding="utf-8") as f:
        f.write(f"# Problem statement — {feature_id}\n\n{r['problem_statement']}\n")
    with open(os.path.join(specs_dir, "spec.md"), "w", encoding="utf-8") as f:
        f.write(_render_spec(feature_id, r))
    with open(os.path.join(specs_dir, "po-validation.md"), "w", encoding="utf-8") as f:
        f.write(_render_po(r))
    if verdict_dir:
        os.makedirs(verdict_dir, exist_ok=True)
        verdict = "PASS" if r["po"]["pass"] else "REVISE"
        with open(os.path.join(verdict_dir, "phase-2.md"), "w", encoding="utf-8") as f:
            f.write(f"# PO verdict (phase 2): {verdict}\n\nreviewers: bmad-agent-pm, "
                    f"bmad-validate-prd (DeepSeek R1 ∥ Nemotron Ultra)\n\n"
                    f"gaps: {len(r['po']['gaps'])}\n")


def _render_spec(feature_id, r):
    lines = [f"# Specification — {feature_id}", "",
             "> Drafted by the ADF requirements crew (research-grounded, PO-validated). "
             f"Sources: {', '.join(r['sources']) or 'n/a'}.", "",
             "## Problem statement", "", r["problem_statement"], "",
             "## Requirements (EARS)", ""]
    for i, req in enumerate(r["requirements"], 1):
        rid = req.get("id") or f"REQ-{i:03d}"
        lines.append(f"### {rid}")
        lines.append(f"The system SHALL {req.get('shall', '').lstrip('The system SHALL ').strip()}")
        if req.get("acceptance"):
            lines.append(f"\n**Acceptance:** {req['acceptance']}")
        if req.get("source"):
            lines.append(f"\n*Source:* {req['source']}")
        lines.append("")
    if r["assumptions"]:
        lines += ["## Assumptions", "", *[f"- {a}" for a in r["assumptions"]], ""]
    if r["out_of_scope"]:
        lines += ["## Out of scope", "", *[f"- {o}" for o in r["out_of_scope"]], ""]
    return "\n".join(lines)


def _render_po(r):
    lines = ["# PO validation", "",
             f"**Verdict:** {'PASS ✅' if r['po']['pass'] else 'REVISE ⚠'}", ""]
    if r["po"]["gaps"]:
        lines += ["## Gaps", "", *[f"- {g}" for g in r["po"]["gaps"]], ""]
    if r["open_questions"]:
        lines += ["## Open questions (confirm with the user)", "",
                  *[f"- {q}" for q in r["open_questions"]], ""]
    if r["improvements"]:
        lines += ["## Suggested improvements", "", *[f"- {i}" for i in r["improvements"]], ""]
    if r["cross_check"]:
        lines += ["## Adversarial cross-check", "", *[f"- {i}" for i in r["cross_check"]], ""]
    return "\n".join(lines)
