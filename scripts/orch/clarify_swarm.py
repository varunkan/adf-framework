#!/usr/bin/env python3
"""ADF clarify-and-verify SWARM — split → free workers → converge.

A HIGH-POWER splitter (Opus) explodes a requirement into 100s-1000s of small, atomic
research + verification TASKS; ONE FREE-model worker runs each task (the massive parallel
muscle); a HIGH-POWER converger (Opus) merges the results into clarified + verified
requirements. HIERARCHICAL (map-reduce: split→areas, expand→tasks, work→per-task,
reduce→per-area, converge→final) so the Opus heads stay context-bounded even at 1000s of
tasks. Reuses build_crew.run_crew (parallel + rate-limit-resilient via model_router) +
web_scraper (optional per-task research).

  run(requirement, complete=None, gather=None, areas=None, tasks_per_area=None,
      parallelism=None, env=None) -> {requirements, open_questions, risks, stats}

`complete(prompt, role, system=None)` (default model_router.complete) and
`gather(queries, urls)` (default web_scraper.gather) are injectable for tests. The heads
use roles 'split'/'converge' (Opus, free DeepSeek fallback); workers use free roles.
"""
import json
import os
import re
import sys
import time

import build_crew


def _log(msg):
    """Live progress line (stderr so it never pollutes the JSON result on stdout)."""
    sys.stderr.write(f"[swarm] {msg}\n")
    sys.stderr.flush()


# --- injectable defaults -------------------------------------------------------

def _complete(prompt, role, system=None):
    import model_router
    res = model_router.complete(prompt, role, system=system)
    return (res[0] if res else "") or ""


def _gather(queries, urls):
    import web_scraper
    import model_router
    return web_scraper.gather(queries=queries, urls=urls,
                              complete=lambda p, r: model_router.complete(p, r))


def _json(text, default):
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


def _scale(env):
    """Areas × tasks-per-area, auto-scaled by track (overridable). S→~50, M→~300,
    L/XL→~900 worker tasks."""
    track = (env.get("ADF_TRACK") or "M").upper()
    by_track = {"S": (6, 8), "M": (15, 20), "L": (30, 30), "XL": (30, 34)}
    a, t = by_track.get(track, (15, 20))
    return (int(env.get("ADF_SWARM_AREAS", a)),
            int(env.get("ADF_SWARM_TASKS_PER_AREA", t)))


_SPLIT_SYS = ("You are a principal requirements strategist. List the distinct "
              "research/verification AREAS needed to cover the request EXHAUSTIVELY "
              "before any code (functional scope, data model, user roles, security, "
              "compliance, integrations, NFRs, edge cases, UX, deployment, …). Output ONE "
              "area PER LINE as 'Area name — one-line focus'. No JSON, no numbering, no "
              "preamble — just the lines. (Line format parses reliably even on free "
              "models; a giant nested-JSON object does not.)")

_EXPAND_SYS = ("Break this ONE area into small, ATOMIC tasks — each a single thing to "
               "RESEARCH (a fact/standard/constraint to find) or VERIFY (a claim/"
               "requirement to check). Specific, answerable, non-overlapping. Output ONE "
               "task PER LINE as 'research: <task>' or 'verify: <task>'. No JSON, no "
               "preamble — just the lines.")


_LEAD = re.compile(r"^[\s\-\*••\d\.\)]+")
_SKIP = ("here ", "below", "the following", "areas", "tasks", "sure", "okay", "###")


def _parse_areas(text, n):
    """Areas from the splitter — JSON if it returned JSON, else one-per-line
    'Name — focus' (robust on free models). Returns [{area, focus}]."""
    j = _json(text, None)
    if isinstance(j, dict) and j.get("areas"):
        return [{"area": str(a.get("area", "")).strip()[:60],
                 "focus": str(a.get("focus", "")).strip()}
                for a in j["areas"] if a.get("area")][:n]
    out = []
    for ln in (text or "").splitlines():
        s = _LEAD.sub("", ln).strip()
        if len(s) < 3 or s.lower().startswith(_SKIP) or s.startswith(("{", "}", "[")):
            continue
        parts = re.split(r"\s[—–:\-]\s", s, maxsplit=1)
        name = parts[0].strip().strip('"').strip()[:60]
        if len(name) > 2:
            out.append({"area": name, "focus": (parts[1].strip() if len(parts) > 1 else "")})
    return out[:n]


def _parse_tasks(text, n):
    """Tasks from an expand agent — 'research:/verify:' lines (JSON tolerated)."""
    j = _json(text, None)
    if isinstance(j, dict) and j.get("tasks"):
        return [{"type": (t.get("type") or "verify").lower(), "task": str(t.get("task", "")).strip()}
                for t in j["tasks"] if t.get("task")][:n]
    out = []
    for ln in (text or "").splitlines():
        s = _LEAD.sub("", ln).strip()
        if len(s) < 6 or s.lower().startswith(_SKIP) or s.startswith(("{", "}", "[")):
            continue
        m = re.match(r"(research|verify)\s*[:\-)]\s*(.+)", s, re.I)
        if m:
            out.append({"type": m.group(1).lower(), "task": m.group(2).strip().strip('"')})
        elif len(s) > 10:
            out.append({"type": "verify", "task": s.strip('"')})
    return out[:n]

_WORK_SYS = ("Do this ONE small task for a software requirement. Be terse + concrete. If "
             "you cannot answer confidently, say what must be CLARIFIED with the product "
             'owner. Reply ONLY JSON: {"finding":"<answer or fact>","clarify":"<a '
             'question for the owner, or empty>"}')

_REDUCE_SYS = ("Merge these task findings for ONE area into a compact summary. Reply ONLY "
               'JSON: {"facts":[..key verified facts..],"clarifications":[..owner '
               'questions..],"risks":[..]}')

_CONVERGE_SYS = ("You are a principal engineer (HIGH POWER) converging many area findings "
                 "into the FINAL requirements. Dedupe + resolve conflicts; every "
                 "requirement measurable + testable. Reply ONLY JSON: "
                 '{"requirements":[{"id","shall","acceptance"}],'
                 '"open_questions":[{"question","why","options":[..]}],"risks":[..]}')


def run(requirement, complete=None, gather=None, areas=None, tasks_per_area=None,
        parallelism=None, env=None):
    complete = complete or _complete
    gather = gather or _gather
    env = env if env is not None else os.environ
    os.environ.setdefault("ADF_NVIDIA_TIMEOUT_SEC", "240")
    n_areas, n_tasks = _scale(env)
    if areas is not None:
        n_areas = areas
    if tasks_per_area is not None:
        n_tasks = tasks_per_area
    par = int(parallelism or env.get("ADF_SWARM_PARALLELISM", "8"))

    # 1) SPLIT (head) → areas (line-tolerant parse — robust on free models at scale)
    split_txt = complete(
        f"REQUEST:\n{requirement}\n\nList up to {n_areas} areas.", "split", _SPLIT_SYS)
    area_list = _parse_areas(split_txt, n_areas) or [
        {"area": "functional scope", "focus": requirement[:120]}]
    _log(f"SPLIT → {len(_uniq(area_list))} areas (free heads + free workers, par={par})")

    # 2) EXPAND (free, one agent per area) → atomic tasks
    def run_expand(agent, prior):
        a = next(x for x in area_list if x["area"] == agent.name)
        out = complete(
            f"AREA: {a['area']} — {a.get('focus','')}\nREQUEST: {requirement}\n"
            f"List up to {n_tasks} atomic tasks.", "draft", _EXPAND_SYS)
        return True, [(agent.name, out)], agent.name
    exp = build_crew.run_crew(
        [build_crew.BuildAgent(a["area"], a["area"]) for a in _uniq(area_list)],
        run_expand, parallelism=par)
    tasks = []
    for area_name, out in exp["files"].items():
        for t in _parse_tasks(out, n_tasks):
            tasks.append({"id": f"t{len(tasks)}", "area": area_name,
                          "task": t["task"], "type": t.get("type", "verify")})

    _log(f"EXPAND → {len(tasks)} atomic tasks → spinning {len(tasks)} worker agents")

    # 3) WORK (free, ONE agent per task — the massive parallel layer)
    by_id = {t["id"]: t for t in tasks}
    _work_t0 = time.time()

    def run_work(agent, prior):
        t = by_id[agent.name]
        prompt = f"REQUIREMENT: {requirement}\nTASK ({t['type']}): {t['task']}"
        if t["type"] == "research" and t["task"].strip().lower().startswith("http"):
            notes = gather([], [t["task"].strip()])
            ctx = "\n".join(n.get("facts", "")[:400] for n in notes[:1])
            if ctx:
                prompt += "\nCONTEXT:\n" + ctx
        role = "verify" if t["type"] == "verify" else "extract"
        out = complete(prompt, role, _WORK_SYS)
        return True, [(agent.name, out)], agent.name
    work = build_crew.run_crew(
        [build_crew.BuildAgent(t["id"], t["id"]) for t in tasks], run_work,
        parallelism=par) if tasks else {"files": {}}

    _log(f"WORK → {len(work['files'])}/{len(tasks)} workers returned "
         f"in {time.time() - _work_t0:.0f}s")

    # 4) REDUCE (free, one agent per area) → area finding (collapses 1000s → ~N)
    def run_reduce(agent, prior):
        items = [(by_id[i]["task"], _json(o, {"finding": o}))
                 for i, o in work["files"].items() if by_id[i]["area"] == agent.name]
        blob = "\n".join(
            f"- {q}: {f.get('finding','')} {('[CLARIFY: '+f['clarify']+']') if f.get('clarify') else ''}"
            for q, f in items)[:7000]
        out = complete(f"AREA: {agent.name}\nFINDINGS:\n{blob}", "draft", _REDUCE_SYS)
        return True, [(agent.name, out)], agent.name
    red = build_crew.run_crew(
        [build_crew.BuildAgent(a["area"], a["area"]) for a in _uniq(area_list)],
        run_reduce, parallelism=par)

    # 5) CONVERGE (Opus head) → final
    findings = "\n\n".join(f"## {a}\n{o}" for a, o in red["files"].items())[:12000]
    final = _json(complete(
        f"REQUEST: {requirement}\n\nAREA FINDINGS:\n{findings}", "converge", _CONVERGE_SYS),
        {"requirements": [], "open_questions": [], "risks": []})

    return {
        "requirement": requirement,
        "requirements": final.get("requirements") or [],
        "open_questions": final.get("open_questions") or [],
        "risks": final.get("risks") or [],
        "stats": {"areas": len(_uniq(area_list)), "tasks": len(tasks),
                  "workers_run": len(work["files"]),
                  "model": "Opus heads + free NVIDIA workers"},
    }


def _uniq(area_list):
    seen, out = set(), []
    for a in area_list:
        if a["area"] not in seen:
            seen.add(a["area"])
            out.append(a)
    return out
