#!/usr/bin/env python3
"""Parallel build crew for ADF's implement phase — decompose a build into fresh-context
subagents that run in dependency-ordered parallel waves.

Superpowers' subagent-driven development + dispatching-parallel-agents, applied to Phase
7. Today Phase 7 is ONE LLM call for the whole app; this splits it into focused
subagents (data layer / API / tests / UI), each with its OWN fresh context — its spec
slice + the files earlier waves wrote (the app dir IS the shared memory, no message
passing). Waves run concurrently (ThreadPoolExecutor; model calls are I/O-bound). The
Kahn scheduler is a faithful port of agent_crew.dart's buildExecutionWaves, so the two
stay in lockstep — same self-dep / unknown-dep / cycle errors, validated before any
agent runs.

DESIGN — decompose to GENERATE; unify to VERIFY + HEAL: the authoritative gate stays the
whole-app verify_app after the last wave (a subagent never seals), and any empty/failed
wave degrades to the monolithic path (ADF_BUILD_CREW=fallback) so a crew bug never
strands a build. Pure + injection-based (run_agent is passed in) so scheduling + merge
are unit-testable without a model.

  build_execution_waves(agents)     -> [[name,...], ...]   (Kahn; validated)
  decomposition_for(stack)          -> [BuildAgent] | None
  run_crew(agents, run_agent, ...)  -> {files, waves, blockers}
"""
import concurrent.futures
import fnmatch
import os


def matches_globs(path, globs):
    """True if `path` matches any of `globs` (a subagent's emit_globs). Lenient by
    design — `**` is normalized to `*`, and fnmatch's `*` crosses `/`, so
    'src/**.tsx' routes 'src/components/App.tsx' to the ui agent. A path matching no
    glob is kept anyway by the caller (over-emission is defensive, not fatal)."""
    p = (path or "").replace("\\", "/")
    return any(fnmatch.fnmatch(p, g.replace("**", "*")) for g in (globs or []))


class BuildAgent:
    """One subagent in the build DAG: a name, the upstream agents it needs, the file
    globs it owns (its slice of the app), and an optional prompt builder."""
    __slots__ = ("name", "role", "needs", "emit_globs", "prompt_fn")

    def __init__(self, name, role, needs=None, emit_globs=None, prompt_fn=None):
        self.name = name
        self.role = role
        self.needs = list(needs or [])
        self.emit_globs = list(emit_globs or [])
        self.prompt_fn = prompt_fn


def build_execution_waves(agents):
    """Plan parallel execution waves (Kahn's algorithm) with EXPLICIT validation — a
    faithful port of agent_crew.dart buildExecutionWaves. Each wave is the set of agents
    whose deps are all met by earlier waves, so a wave runs fully in parallel. Raises
    ValueError naming the offenders on a self-dependency, an unknown dependency, or a
    cycle — never a silent empty wave mid-run."""
    names = {a.name for a in agents}
    deps = {}
    for a in agents:
        if a.name in a.needs:
            raise ValueError(f'build agent "{a.name}" depends on itself')
        for n in a.needs:
            if n not in names:
                raise ValueError(f'build agent "{a.name}" needs unknown agent "{n}"')
        deps[a.name] = set(a.needs)
    done, waves = set(), []
    remaining = [a.name for a in agents]
    while remaining:
        wave = [n for n in remaining if deps[n] <= done]
        if not wave:
            raise ValueError("build dependency cycle among: " + ", ".join(remaining))
        waves.append(wave)
        done.update(wave)
        wave_set = set(wave)
        remaining = [n for n in remaining if n not in wave_set]
    return waves


def is_enabled(env=None):
    env = env if env is not None else os.environ
    return env.get("ADF_BUILD_CREW", "").strip().lower() in (
        "1", "on", "fallback", "strict")


def allows_fallback(env=None):
    """True unless ADF_BUILD_CREW=strict — i.e. a crew failure degrades to the
    monolithic path by default rather than failing the build."""
    env = env if env is not None else os.environ
    return env.get("ADF_BUILD_CREW", "").strip().lower() != "strict"


def _react_crew():
    return [
        BuildAgent("data-layer", "SQLite schema + typed data access", needs=[],
                   emit_globs=["schema.sql", "src/db.ts"]),
        BuildAgent("api-routes", "Fastify REST routes under /api",
                   needs=["data-layer"], emit_globs=["server/api/*.mjs", "server/**.mjs"]),
        BuildAgent("test-author", "vitest suite (the RED for TDD)",
                   needs=["data-layer"], emit_globs=["test/*.test.mjs"]),
        BuildAgent("ui", "React + Tailwind components and screens",
                   needs=["api-routes"], emit_globs=["src/**.tsx", "src/**.ts"]),
    ]


# Stacks with a decomposition; stdlib (tiny, single-file) stays monolithic (None).
_DECOMPOSITIONS = {
    "react-vite-sqlite": _react_crew,
}


def decomposition_for(stack):
    fn = _DECOMPOSITIONS.get(stack)
    return fn() if fn else None


def run_crew(agents, run_agent, parallelism=3):
    """Execute the DAG in parallel waves. `run_agent(agent, prior)` is INJECTED: it
    builds + writes the agent's slice and returns (ok, files, detail) where `files` is a
    list of (path, content); `prior` is the accumulated files map from earlier waves.
    Returns {files, waves, blockers}. A failing agent is recorded as a blocker but its
    siblings in the wave still run (matching the Dart crew's collect-then-stop) — the
    caller decides fallback vs whole-app heal."""
    plan = build_execution_waves(agents)
    by_name = {a.name: a for a in agents}
    files, waves, blockers = {}, [], []
    for wave_names in plan:
        waves.append(list(wave_names))
        prior = dict(files)
        results = {}
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, parallelism)) as ex:
            futs = {ex.submit(run_agent, by_name[n], prior): n for n in wave_names}
            for fut in concurrent.futures.as_completed(futs):
                n = futs[fut]
                try:
                    ok, agent_files, detail = fut.result()
                except Exception as e:  # noqa: BLE001 — one agent must not kill the wave
                    ok, agent_files, detail = False, [], f"{n} errored: {e}"
                results[n] = (ok, agent_files, detail)
                if not ok:
                    blockers.append(detail or n)
        # Merge in deterministic wave order (not completion order) for reproducibility.
        for n in wave_names:
            _ok, agent_files, _detail = results[n]
            for p, c in (agent_files or []):
                files[p] = c
    return {"files": files, "waves": waves, "blockers": blockers}
