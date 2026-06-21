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
           "draft for the given lens. Flag any SOURCE CONFLICT (two sources disagree) as a "
           "gap — never let it pass silently. Reply ONLY JSON: "
           '{"pass":bool,"gaps":[..specific issues..]}')

_Q_SYS = ("You are the BMAD PO facilitating requirements confirmation. From the draft + "
          "gaps, list what is genuinely AMBIGUOUS and needs the user's decision, plus "
          'improvement suggestions. Reply ONLY JSON: {"questions":[..],"improvements":[..]}')

_HEAD_SYS = ("You are a principal engineer synthesizing ONE coherent PRD from many "
             "fragments (BMAD create-prd discipline): consolidate, DEDUPE, ensure every "
             "requirement is measurable + testable + traceable + cited, integrate the PO "
             "gaps, and rank source authority (user docs/mockups > web). CONFLICT POLICY = "
             "ASK: when sources DISAGREE, do NOT silently pick a winner — surface the "
             "conflict verbatim as an open_question for the user to decide. Reply ONLY JSON: "
             '{"problem_statement","requirements":[{"id","shall","acceptance","source"}],'
             '"assumptions":[],"out_of_scope":[],"open_questions":[]}')

_XCHECK_SYS = ("You are an adversarial reviewer (different model than the author). Try to "
               "REFUTE the PRD: missing requirements, untestable claims, unsourced domain "
               'facts, source conflicts. Reply ONLY JSON: {"issues":[..]}')


def _corpus_text(corpus, limit=9000):
    import compaction
    out = []
    for n in corpus:
        out.append(f"### {n.get('title','')} ({n.get('url','')})\n{n.get('facts','')}")
    # head+tail compaction so the LAST scraped sources aren't silently dropped.
    return compaction.clip("\n\n".join(out), limit)


def _headroom(value, limit=3000):
    """Bound any list/text fed into a HEAD (synthesis/questions) so a large run can't
    blow the context window — context compaction at the wave boundary. Delegates to
    the canonical compaction.clip (head+tail), not a blind truncate."""
    import compaction
    return compaction.clip(value, limit)


def run(feature_id, requirement, sources=None, specs_dir=None, verdict_dir=None,
        complete=None, gather=None, parallelism=4):
    """Run the crew. `sources` is a list of pre-ingested {source, requirements} dicts
    (docs/data/repo) + optional {url} entries. Returns the result dict and writes the
    spec artifacts. complete/gather injectable for tests."""
    complete = complete or _complete
    gather = gather or _gather
    sources = sources or []
    # Reasoning models (DeepSeek/Qwen) need real time to think — the default 75s
    # NVIDIA cap (tuned to fail-fast in the build loop) makes the planner/PO time out and
    # return nothing. The crew has no faster fallback here, so give it room (set once,
    # before any threads). Respects an explicit override.
    os.environ.setdefault("ADF_NVIDIA_TIMEOUT_SEC", "240")
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
    draft_text = _headroom(all_reqs, 9000)

    # Wave 3a — PO validation (perspective-diverse: R1 rigor ∥ Ultra judge, parallel)
    def run_po(agent, prior):
        role = "verify" if agent.name == "rigor" else "judge"
        lens = ("measurability, testability, traceability, completeness"
                if agent.name == "rigor"
                else "domain-compliance, holistic coherence, source reconciliation")
        out = complete(f"LENS: {lens}\nDRAFT:\n{draft_text}\n\nSOURCES: {sources_list}",
                       role, _PO_SYS)
        return True, [(agent.name, out)], agent.name
    po_agents = [build_crew.BuildAgent(n, n) for n in ("rigor", "judge")]
    po_res = build_crew.run_crew(po_agents, run_po, parallelism=parallelism)
    rigor = _json(po_res["files"].get("rigor", ""), {"pass": True, "gaps": []})
    judge = _json(po_res["files"].get("judge", ""), {"pass": True, "gaps": []})
    # perspective-diverse: a gap counts if EITHER reasoner flags it
    po_gaps = list(rigor.get("gaps") or []) + list(judge.get("gaps") or [])
    po_pass = bool(rigor.get("pass")) and bool(judge.get("pass")) and not po_gaps

    # Wave 3b — clarifying questions (DAG edge: DEPENDS on the PO gaps, so it can
    # ask about exactly what the PO flagged — was wrongly run blind in parallel).
    qs = _json(complete(
        f"DRAFT:\n{draft_text}\n\nPO GAPS (focus the questions on these):\n"
        f"{_headroom(po_gaps)}", "questions", _Q_SYS),
        {"questions": [], "improvements": []})

    # Wave 4 — synthesis head (Opus) + adversarial cross-check (R1). Head inputs are
    # headroom-capped so a big run can't blow the context.
    head = _json(complete(
        f"REQUEST: {requirement}\nCATEGORIES: {categories}\nDRAFTS:\n{draft_text}\n\n"
        f"PO GAPS:\n{_headroom(po_gaps)}\n\nCORPUS:\n{corpus_text}\n\n"
        f"SOURCES: {_headroom(sources_list, 1500)}",
        "synthesis", _HEAD_SYS),
        {"problem_statement": requirement, "requirements": all_reqs,
         "assumptions": [], "out_of_scope": [], "open_questions": []})
    xcheck = _json(complete(f"PRD:\n{_headroom(head, 9000)}", "cross_check", _XCHECK_SYS),
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
            # The "**Reviewers:**" line is a CONTRACT with the Dart gate's
            # parseReviewerSkills (feature_store.dart) — keep the exact prefix +
            # bare, comma-separated skills (model attribution on its own line, so it
            # is NOT parsed as a skill). The live E2E caught the old lowercase format.
            f.write(f"# PO verdict (phase 2): {verdict}\n\n"
                    f"**Reviewers:** bmad-agent-pm, bmad-validate-prd\n"
                    f"_(perspective-diverse: DeepSeek R1 ∥ Nemotron Ultra)_\n\n"
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
        # Strip any leading "The system SHALL/shall " PREFIX (not chars) so we don't
        # double it or mangle the first word (lstrip is a char-set, not a prefix).
        shall = re.sub(r"^\s*the system shall\s+", "", req.get("shall", "").strip(),
                       flags=re.I)
        lines.append(f"The system SHALL {shall}")
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
        lines += ["## Gaps", "", *[f"- {_g(g)}" for g in r["po"]["gaps"]], ""]
    if r["open_questions"]:
        lines += ["## Open questions (confirm with the user)", "",
                  *[f"- {_g(q)}" for q in r["open_questions"]], ""]
    if r["improvements"]:
        lines += ["## Suggested improvements", "", *[f"- {_g(i)}" for i in r["improvements"]], ""]
    if r["cross_check"]:
        lines += ["## Adversarial cross-check", "", *[f"- {_g(i)}" for i in r["cross_check"]], ""]
    return "\n".join(lines)


def _g(x):
    """A model may return a gap/question as a string OR a {question/description/...}
    dict — render either to one human line."""
    if isinstance(x, dict):
        return (x.get("question") or x.get("description") or x.get("issue")
                or x.get("suggestion") or json.dumps(x))
    return str(x)


# --- CLI: invoked by the Dart orchestrator for phases 1-2 (like agent_runner) ----

_CMD_LEAK = re.compile(r"^\s*@orch-orchestrator.*$|^\s*#\s*Builder:.*$", re.M)


def clean_requirement(raw):
    """Strip markdown scaffolding + the orchestrator command spam that leaks into
    requirement.md (so the crew never ingests '@orch-orchestrator resume …' as a
    requirement — the exact bug that produced the garbage spec)."""
    raw = _CMD_LEAK.sub("", raw or "")
    keep = []
    for ln in raw.splitlines():
        s = ln.strip()
        if s.startswith("#") or re.match(r"^\*\*[^*]+:\*\*", s) or re.match(r"^[-=*_]{3,}$", s):
            continue
        keep.append(ln)
    return "\n".join(keep).strip()


def _load_sources(repo_root, sources_path):
    """Read a sources.json the server wrote (docs/links/data/...) and pre-ingest the
    document/data ones via doc_ingest; pass url/link entries through."""
    if not sources_path or not os.path.isfile(sources_path):
        return []
    try:
        raw = json.load(open(sources_path, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for s in raw if isinstance(raw, list) else []:
        if s.get("url") or s.get("link"):
            out.append({"url": s.get("url") or s.get("link")})
        elif s.get("path"):
            try:
                import doc_ingest
                out.append(doc_ingest.ingest(
                    s["path"], complete=lambda p, r: _model_tuple(p, r)))
            except Exception:  # noqa: BLE001
                pass
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("feature_id")
    ap.add_argument("--workspace", default=os.getcwd())
    ap.add_argument("--sources", default=None)
    args, _ = ap.parse_known_args()

    import agent_runner
    repo_root = os.environ.get("ORCH_REPO_ROOT", os.path.abspath(args.workspace))
    agent_runner.load_env(repo_root)
    fid = args.feature_id

    req = ""
    for d in (".cursor/orchestration", ".claude/orchestration", "orchestration"):
        p = os.path.join(repo_root, d, "features", fid, "requirement.md")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                req = f.read()
            break
    req = clean_requirement(req) or fid

    sources = _load_sources(repo_root, args.sources)
    specs_dir = os.path.join(repo_root, "specs", fid)
    verdict_dir = os.path.join(repo_root, ".cursor", "orchestration", "features", fid,
                               "judge-verdicts")
    res = run(fid, req, sources=sources, specs_dir=specs_dir, verdict_dir=verdict_dir)
    print(json.dumps({
        "feature_id": fid, "requirements": len(res["requirements"]),
        "po_pass": res["po"]["pass"], "gaps": len(res["po"]["gaps"]),
        "open_questions": len(res["open_questions"]), "sources": res["sources"],
        # The actual question STRINGS (capped) so the gate can present them to the
        # user for interactive confirmation (P3), not just a count.
        "questions": [_g(q) for q in res["open_questions"]][:10]}))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
